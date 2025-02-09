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
    validate_quiz_setup
)
from model import get_llm, LLMProvider
from utils.errors import NoQuestionsError, NoResponsesError, InvalidQuestionError, ResponseQuestionMismatchError


@pytest.fixture
def redis_mock():
    redis_client = MagicMock(spec=Redis)
    redis_client.get.return_value = None
    return redis_client

@pytest.fixture
def pg_cursor_mock():
    cursor = MagicMock()
    cursor.fetchall.return_value = [{
        "id": "test_response_1",
        "studentId": "test_student_1",
        "quizId": "test_quiz1",
        "score": 0,
        "submittedAt": "2025-01-07 10:25:44.442000",
        "responses": {},
        "violations": "",
        "totalScore": 10.0,
    }]
    return cursor

@pytest.fixture
def mongo_db_mock():
    db = MagicMock()
    db['NEW_QUESTIONS'].find.return_value = [{
        '_id': 'q1',
        'quizId': 'quiz1',
        'question': 'Test question?',
        'type': 'DESCRIPTIVE',
        'expectedAnswer': ['Expected answer'],
        'marks': 10,
        'guidelines': 'Test guidelines'
    }]
    return db

@pytest.mark.asyncio
async def test_get_guidelines(redis_mock):
    """Test guidelines generation and caching"""
    llm = get_llm(LLMProvider.GROQ)
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
    mongo_db_mock['NEW_QUESTIONS'].find.assert_called_once()
    assert len(questions) > 0
    
    # Verify cache was set with correct prefix
    redis_mock.set.assert_called_once()
    cache_key = redis_mock.set.call_args[0][0]
    assert cache_key == f"questions:{quiz_id}_questions_evalcache"

@pytest.mark.asyncio
async def test_bulk_evaluate_quiz_responses(redis_mock, pg_cursor_mock, mongo_db_mock):
    """Test bulk evaluation of quiz responses"""
    quiz_id = "test_quiz1"
    pg_conn_mock = MagicMock()
    
    # Perform bulk evaluation
    results = await bulk_evaluate_quiz_responses(
        quiz_id, pg_cursor_mock, pg_conn_mock, mongo_db_mock, redis_mock
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
    mock_data = [{
        "id": "test_response_1",
        "studentId": "test_student_1",
        "quizId": "test_quiz1",
        "score": 0,
        "submittedAt": "2025-01-07 10:25:44.442000",
        "responses": {},
        "violations": "",
        "totalScore": 10.0,
    }]
    
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
    mongo_db_mock['NEW_QUESTIONS'].find.return_value = []
    quiz_id = "empty_quiz"
    
    questions = get_all_questions(mongo_db_mock, redis_mock, quiz_id)
    assert isinstance(questions, list)
    assert len(questions) == 0

@pytest.mark.asyncio
async def test_guidelines_error_handling(redis_mock):
    """Test error handling in guidelines generation"""
    llm = MagicMock()
    llm.ainvoke.side_effect = Exception("Test API Error")
    
    result = await get_guidelines(
        redis_client=redis_mock,
        llm=llm,
        question_id="q1",
        question="test question",
        expected_answer="test answer",
        total_score=10
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
        "totalScore": 10
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
    responses = [{"id": "1", "responses": {"q2": {"student_answer": "A"}}}]  # Question ID 'q2' not in questions
    
    with pytest.raises(ResponseQuestionMismatchError):
        await validate_quiz_setup(quiz_id, questions, responses)
