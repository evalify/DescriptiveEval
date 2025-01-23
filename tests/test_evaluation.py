import json
from unittest.mock import MagicMock

import pytest
from redis import Redis

from evaluation import (
    get_guidelines,
    get_quiz_responses,
    get_all_questions,
    bulk_evaluate_quiz_responses,
    CACHE_EX
)
from model import get_llm, LLMProvider


@pytest.fixture
def redis_mock():
    redis_client = MagicMock(spec=Redis)
    redis_client.get.return_value = None
    return redis_client


@pytest.fixture
def pg_cursor_mock():
    cursor = MagicMock()
    cursor.fetchall.return_value = [{
        'id': '1',
        'studentId': 'student1',
        'quizId': 'quiz1',
        'responses': {'q1': ['answer1']},
        'submittedAt': '2024-01-01',
        'questionMarks': {},
        'score': 0,
        'remarks': None
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
        'explanation': ['Expected answer'],
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

    # Verify cache was set
    redis_mock.set.assert_called_once()
    cache_key = redis_mock.set.call_args[0][0]
    assert cache_key == f"{question_id}_guidelines_cache"


@pytest.mark.asyncio
async def test_get_quiz_responses(redis_mock, pg_cursor_mock):
    """Test quiz response retrieval and caching"""
    quiz_id = "test_quiz1"

    # Get responses
    responses = get_quiz_responses(pg_cursor_mock, redis_mock, quiz_id)

    # Verify database was queried
    pg_cursor_mock.execute.assert_called_once()
    assert len(responses) > 0

    # Verify cache was set
    redis_mock.set.assert_called_once()
    cache_key = redis_mock.set.call_args[0][0]
    assert cache_key == f"{quiz_id}_responses_evalcache"


@pytest.mark.asyncio
async def test_get_all_questions(redis_mock, mongo_db_mock):
    """Test question retrieval and caching"""
    quiz_id = "test_quiz1"

    # Get questions
    questions = get_all_questions(mongo_db_mock, redis_mock, quiz_id)

    # Verify database was queried
    mongo_db_mock['NEW_QUESTIONS'].find.assert_called_once()
    assert len(questions) > 0

    # Verify cache was set
    redis_mock.set.assert_called_once()
    cache_key = redis_mock.set.call_args[0][0]
    assert cache_key == f"{quiz_id}_questions_evalcache"


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

    # Set cache with expiration
    redis_mock.get.return_value = json.dumps({"test": "data"})

    # Get cached data
    responses = get_quiz_responses(MagicMock(), redis_mock, quiz_id)
    assert responses == {"test": "data"}

    # Verify expiration was set correctly
    redis_mock.set.assert_not_called()  # Should use cached value

    # Simulate cache expiration
    redis_mock.get.return_value = None
    responses = get_quiz_responses(MagicMock(), redis_mock, quiz_id)

    # Verify new cache was set with correct expiration
    redis_mock.set.assert_called_once()
    assert redis_mock.set.call_args[1]['ex'] == CACHE_EX


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
    llm.ainvoke.side_effect = Exception("API Error")

    result = await get_guidelines(
        redis_mock, llm, "q1", "question", "answer", 10
    )
    assert "Error processing response" in result["guidelines"]
