import json
from unittest.mock import MagicMock

import pytest
from redis import Redis

from evaluation import (
    get_guidelines,
    get_quiz_responses,
    get_all_questions,
    bulk_evaluate_quiz_responses,
    set_quiz_response,
    validate_quiz_setup,
)
from utils.errors import (
    NoQuestionsError,
    NoResponsesError,
    InvalidQuestionError,
    ResponseQuestionMismatchError,
)
from utils.quiz.quiz_report import generate_quiz_report, save_quiz_report


@pytest.fixture
def redis_mock():
    redis_client = MagicMock(spec=Redis)
    redis_client.get.return_value = None
    return redis_client


@pytest.fixture
def pg_cursor_mock():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {
            "id": "test_response_1",
            "studentId": "test_student_1",
            "quizId": "test_quiz1",
            "score": 0,
            "submittedAt": "2025-01-07 10:25:44.442000",
            "responses": {},
            "violations": "",
            "totalScore": 10.0,
        }
    ]
    return cursor


@pytest.fixture
def mongo_db_mock():
    db = MagicMock()
    db["NEW_QUESTIONS"].find.return_value = [
        {
            "_id": "q1",
            "quizId": "quiz1",
            "question": "Test question?",
            "type": "DESCRIPTIVE",
            "expectedAnswer": ["Expected answer"],
            "marks": 10,
            "guidelines": "Test guidelines",
        }
    ]
    return db


@pytest.mark.asyncio
async def test_get_guidelines(redis_mock, llm):
    """Test guidelines generation and caching"""
    question_id = "test_q1"
    question = "What is photosynthesis?"
    expected_answer = "Process of converting light to energy"
    total_score = 10

    # First call - should generate guidelines
    result = await get_guidelines(
        redis_mock, llm, question_id, question, expected_answer, total_score
    )
    assert isinstance(result, dict)
    assert "guidelines" in result

    # Verify cache was set with correct prefix
    redis_mock.set.assert_called_once()
    cache_key = redis_mock.set.call_args[0][0]
    assert cache_key == f"guidelines:{question_id}_guidelines_cache"


@pytest.mark.asyncio
async def test_get_quiz_responses(redis_mock, pg_cursor_mock):
    """Test quiz response retrieval and caching"""
    quiz_id = "test_quiz1"

    # Get responses
    responses = get_quiz_responses(pg_cursor_mock, redis_mock, quiz_id)

    # Verify database was queried
    pg_cursor_mock.execute.assert_called_once()
    assert len(responses) > 0

    # Verify cache was set with correct prefix
    redis_mock.set.assert_called_once()
    cache_key = redis_mock.set.call_args[0][0]
    assert cache_key == f"responses:{quiz_id}_responses_evalcache"


@pytest.mark.asyncio
async def test_get_all_questions(redis_mock, mongo_db_mock):
    """Test question retrieval and caching"""
    quiz_id = "test_quiz1"

    # Get questions
    questions = get_all_questions(mongo_db_mock, redis_mock, quiz_id)

    # Verify database was queried
    mongo_db_mock["NEW_QUESTIONS"].find.assert_called_once()
    assert len(questions) > 0

    # Verify cache was set with correct prefix
    redis_mock.set.assert_called_once()
    cache_key = redis_mock.set.call_args[0][0]
    assert cache_key == f"questions:{quiz_id}_questions_evalcache"


@pytest.mark.asyncio
async def test_bulk_evaluate_quiz_responses(
    redis_mock, pg_cursor_mock, mongo_db_mock, llm
):
    """Test bulk evaluation of quiz responses"""
    quiz_id = "test_quiz1"
    pg_conn_mock = MagicMock()

    # Perform bulk evaluation
    results = await bulk_evaluate_quiz_responses(
        quiz_id, pg_cursor_mock, pg_conn_mock, mongo_db_mock, redis_mock, llm=llm
    )

    # Verify results
    assert isinstance(results, list)
    assert len(results) > 0
    assert "score" in results[0]
    assert "remarks" in results[0]


@pytest.mark.asyncio
async def test_cache_expiry(redis_mock):
    """Test Redis cache expiration"""
    quiz_id = "test_quiz1"
    mock_data = [
        {
            "id": "test_response_1",
            "studentId": "test_student_1",
            "quizId": "test_quiz1",
            "score": 0,
            "submittedAt": "2025-01-07 10:25:44.442000",
            "responses": {},
            "violations": "",
            "totalScore": 10.0,
        }
    ]

    # Set up cursor mock with real data
    cursor_mock = MagicMock()
    cursor_mock.fetchall.return_value = mock_data

    # Mock Redis.get to return cached data with correct prefix
    def mock_redis_get(key):
        if key == f"responses:{quiz_id}_responses_evalcache":
            return json.dumps({"test": "data"})
        return None

    redis_mock.get.side_effect = mock_redis_get

    # First call - cache hit
    responses = get_quiz_responses(cursor_mock, redis_mock, quiz_id)
    assert responses == {"test": "data"}

    # Verify expiration was set correctly
    redis_mock.set.assert_not_called()  # Should use cached value

    # Reset mock and simulate cache miss
    redis_mock.get.return_value = None
    responses = get_quiz_responses(cursor_mock, redis_mock, quiz_id)

    # Verify new data was cached with correct prefix
    assert redis_mock.set.call_count == 1
    cache_key = redis_mock.set.call_args[0][0]
    assert cache_key == f"responses:{quiz_id}_responses_evalcache"
    assert isinstance(responses, list)
    assert len(responses) > 0
    assert responses[0]["id"] == "test_response_1"


@pytest.mark.asyncio
async def test_empty_quiz_responses(redis_mock, pg_cursor_mock):
    """Test handling of empty quiz responses"""
    pg_cursor_mock.fetchall.return_value = []
    quiz_id = "empty_quiz"

    responses = get_quiz_responses(pg_cursor_mock, redis_mock, quiz_id)
    assert isinstance(responses, list)
    assert len(responses) == 0


@pytest.mark.asyncio
async def test_empty_questions(redis_mock, mongo_db_mock):
    """Test handling of empty questions"""
    mongo_db_mock["NEW_QUESTIONS"].find.return_value = []
    quiz_id = "empty_quiz"

    questions = get_all_questions(mongo_db_mock, redis_mock, quiz_id)
    assert isinstance(questions, list)
    assert len(questions) == 0


@pytest.mark.asyncio
async def test_guidelines_error_handling(redis_mock, llm):
    """Test error handling in guidelines generation"""
    llm_mock = MagicMock()
    llm_mock.ainvoke.side_effect = Exception("Test API Error")

    result = await get_guidelines(
        redis_client=redis_mock,
        llm=llm_mock,
        question_id="q1",
        question="test question",
        expected_answer="test answer",
        total_score=10,
    )

    # Should return error status and message
    assert result["status"] == 403
    assert "Error" in result.get("guidelines", "")
    assert not redis_mock.set.called  # Should not cache error responses


@pytest.mark.asyncio
async def test_set_quiz_response(pg_cursor_mock):
    """Test setting quiz response in the database"""
    pg_conn_mock = MagicMock()
    response_data = {
        "id": "1",
        "responses": {"q1": {"score": 5}},
        "score": 5,
        "totalScore": 10,
    }

    await set_quiz_response(pg_cursor_mock, pg_conn_mock, response_data)

    # Verify database update
    pg_cursor_mock.execute.assert_called_once()
    pg_conn_mock.commit.assert_called_once()


@pytest.mark.asyncio
async def test_validate_quiz_setup():
    """Test validation of quiz setup"""
    quiz_id = "test_quiz1"
    questions = [{"_id": "q1", "type": "MCQ", "mark": 5, "answer": "A"}]
    responses = [{"id": "1", "responses": {"q1": {"student_answer": "A"}}}]

    await validate_quiz_setup(quiz_id, questions, responses)

    # No exception should be raised for valid setup


@pytest.mark.asyncio
async def test_validate_quiz_setup_no_questions():
    """Test validation of quiz setup with no questions"""
    quiz_id = "test_quiz1"
    questions = []
    responses = [{"id": "1", "responses": {"q1": {"student_answer": "A"}}}]

    with pytest.raises(NoQuestionsError):
        await validate_quiz_setup(quiz_id, questions, responses)


@pytest.mark.asyncio
async def test_validate_quiz_setup_no_responses():
    """Test validation of quiz setup with no responses"""
    quiz_id = "test_quiz1"
    questions = [{"_id": "q1", "type": "MCQ", "mark": 5, "answer": "A"}]
    responses = []

    with pytest.raises(NoResponsesError):
        await validate_quiz_setup(quiz_id, questions, responses)


@pytest.mark.asyncio
async def test_validate_quiz_setup_invalid_question():
    """Test validation of quiz setup with invalid question"""
    quiz_id = "test_quiz1"
    questions = [{"_id": "q1", "type": "MCQ"}]  # Missing 'mark' and 'answer'
    responses = [{"id": "1", "responses": {"q1": {"student_answer": "A"}}}]

    with pytest.raises(InvalidQuestionError):
        await validate_quiz_setup(quiz_id, questions, responses)


@pytest.mark.asyncio
async def test_validate_quiz_setup_response_question_mismatch():
    """Test validation of quiz setup with response question mismatch"""
    quiz_id = "test_quiz1"
    questions = [{"_id": "q1", "type": "MCQ", "mark": 5, "answer": "A"}]
    responses = [
        {"id": "1", "responses": {"q2": {"student_answer": "A"}}}
    ]  # Question ID 'q2' not in questions

    with pytest.raises(ResponseQuestionMismatchError):
        await validate_quiz_setup(quiz_id, questions, responses)


@pytest.mark.asyncio
async def test_mock_quiz_evaluation(redis_mock, pg_cursor_mock, mongo_db_mock, llm, mock_quiz_questions, mock_quiz_responses, mock_quiz_settings):
    """Test complete quiz evaluation flow with mock data"""
    quiz_id = "test-quiz-123"
    pg_conn_mock = MagicMock()

    # Configure mocks to return our mock data
    mongo_db_mock["NEW_QUESTIONS"].find.return_value = mock_quiz_questions
    pg_cursor_mock.fetchall.return_value = mock_quiz_responses

    # Configure evaluation settings mock
    def mock_get_settings(*args):
        return mock_quiz_settings
    pg_cursor_mock.fetchone.side_effect = mock_get_settings

    # Perform bulk evaluation
    results = await bulk_evaluate_quiz_responses(
        quiz_id=quiz_id,
        pg_cursor=pg_cursor_mock,
        pg_conn=pg_conn_mock,
        mongo_db=mongo_db_mock,
        redis_client=redis_mock,
        llm=llm,
        save_to_file=True
    )

    # Verify evaluation results
    assert isinstance(results, list)
    assert len(results) == len(mock_quiz_responses)

    # Verify first student's results (student1)
    student1 = next(r for r in results if r["studentId"] == "student1")
    assert student1["responses"]["q1"]["score"] == 1  # Correct MCQ answer
    assert student1["responses"]["q3"]["score"] == 0  # Wrong True/False answer
    assert student1["responses"]["q3"].get("negative_score", 0) == -0.25  # Negative marking
    assert student1["responses"]["q4"]["score"] == 1  # Correct Fill in Blank
    assert student1["responses"]["q5"]["score"] == 5  # Correct coding solution

    # Verify second student's results (student2)
    student2 = next(r for r in results if r["studentId"] == "student2")
    assert student2["responses"]["q1"]["score"] == 0  # Wrong MCQ answer
    assert student2["responses"]["q1"].get("negative_score", 0) == -0.25  # Negative marking
    assert student2["responses"]["q3"]["score"] == 1  # Correct True/False answer
    assert student2["responses"]["q4"]["score"] == 0  # Wrong Fill in Blank
    assert student2["responses"]["q5"]["score"] == 5  # Correct coding solution (alternate implementation)

    # Verify total scores calculation
    for result in results:
        calculated_score = sum(
            (resp.get("score", 0) + resp.get("negative_score", 0))
            for resp in result["responses"].values()
        )
        assert result["score"] == max(calculated_score, 0)  # Score shouldn't go below 0


@pytest.mark.asyncio
async def test_mock_quiz_report(mock_quiz_questions, mock_quiz_responses):
    """Test quiz report generation with mock data"""
    quiz_id = "test-quiz-123"
    
    # Generate report
    report = await generate_quiz_report(quiz_id, mock_quiz_responses, mock_quiz_questions)
    
    # Verify report structure
    assert isinstance(report, dict)
    assert all(key in report for key in [
        "quizId", "avgScore", "maxScore", "minScore", "totalScore",
        "totalStudents", "questionStats", "markDistribution"
    ])

    # Verify basic statistics
    assert report["quizId"] == quiz_id
    assert report["totalStudents"] == len(mock_quiz_responses)
    assert len(report["questionStats"]) == len(mock_quiz_questions)

    # Verify question statistics
    for stat in report["questionStats"]:
        question = next(q for q in mock_quiz_questions if q["_id"] == stat["questionId"])
        assert stat["maxMarks"] == question["mark"]
        assert "avgMarks" in stat
        assert "totalAttempts" in stat
        assert stat["totalAttempts"] == len(mock_quiz_responses)  # All students attempted all questions

    # Verify mark distribution
    assert all(key in report["markDistribution"] for key in ["excellent", "good", "average", "poor"])
    total_students = sum(report["markDistribution"].values())
    assert total_students == len(mock_quiz_responses)

    # Test report saving
    pg_cursor_mock = MagicMock()
    pg_conn_mock = MagicMock()
    
    await save_quiz_report(quiz_id, report, pg_cursor_mock, pg_conn_mock)
    
    # Verify database operations
    pg_cursor_mock.execute.assert_called_once()
    pg_conn_mock.commit.assert_called_once()


@pytest.mark.asyncio
async def test_selective_question_evaluation(redis_mock, pg_cursor_mock, mongo_db_mock, llm, mock_quiz_questions, mock_quiz_responses, mock_quiz_settings):
    """Test evaluation with selective question types"""
    quiz_id = "test-quiz-123"
    pg_conn_mock = MagicMock()

    # Configure mocks
    mongo_db_mock["NEW_QUESTIONS"].find.return_value = mock_quiz_questions
    pg_cursor_mock.fetchall.return_value = mock_quiz_responses
    pg_cursor_mock.fetchone.return_value = mock_quiz_settings

    # Only evaluate MCQ and TRUE_FALSE questions
    types_to_evaluate = {
        "MCQ": True,
        "DESCRIPTIVE": False,
        "CODING": False,
        "TRUE_FALSE": True,
        "FILL_IN_BLANK": False
    }

    results = await bulk_evaluate_quiz_responses(
        quiz_id=quiz_id,
        pg_cursor=pg_cursor_mock,
        pg_conn=pg_conn_mock,
        mongo_db=mongo_db_mock,
        redis_client=redis_mock,
        llm=llm,
        types_to_evaluate=types_to_evaluate,
        save_to_file=True
    )

    # Verify only selected question types were evaluated
    for result in results:
        for qid, response in result["responses"].items():
            question = next(q for q in mock_quiz_questions if q["_id"] == qid)
            if question["type"] in ["MCQ", "TRUE_FALSE"]:
                assert "score" in response
                if response.get("score", 0) == 0:
                    assert "negative_score" in response
            else:
                # Non-evaluated questions should retain their original state
                assert "score" not in response or response["score"] == 0

    # Generate report for selectively evaluated quiz
    report = await generate_quiz_report(quiz_id, results, mock_quiz_questions)
    
    # Verify report reflects selective evaluation
    for stat in report["questionStats"]:
        question = next(q for q in mock_quiz_questions if q["_id"] == stat["questionId"])
        if question["type"] in ["MCQ", "TRUE_FALSE"]:
            assert stat["totalAttempts"] > 0
        else:
            assert stat["avgMarks"] == 0
