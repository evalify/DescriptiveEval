import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from redis import Redis

from app.api.scoring.service import LLMProvider
from app.api.evaluation.utils.evaluation_job import evaluation_job
from app.api.evaluation.utils.lock import QuizLock


@pytest.fixture
def redis_mock():
    redis_client = MagicMock(spec=Redis)
    redis_client.set.return_value = True  # Simulate successful lock acquisition
    redis_client.delete.return_value = 1  # Simulate successful lock release
    redis_client.exists.return_value = 0  # Initially not locked
    redis_client.ttl.return_value = 3600  # Default TTL

    # Mock cached responses with proper JSON strings
    mock_responses = json.dumps(
        [
            {
                "id": "test_response_1",
                "studentId": "test_student_1",
                "quizId": "test_quiz_1",
                "score": 0,
                "submittedAt": "2025-01-07 10:25:44.442000",
                "responses": {},
                "violations": "",
                "totalScore": 10.0,
            }
        ]
    )

    mock_questions = json.dumps(
        [
            {
                "_id": "test_question_1",
                "quizId": "test_quiz_1",
                "type": "MCQ",
                "question": "Test Question",
                "mark": 10,
                "answer": ["A"],
            }
        ]
    )

    def mock_get(key):
        if key.endswith("_responses_evalcache"):
            return mock_responses
        elif key.endswith("_questions_evalcache"):
            return mock_questions
        return None

    redis_client.get.side_effect = mock_get
    return redis_client


@pytest.fixture
def postgres_mock():
    cursor = MagicMock()
    conn = MagicMock()

    # Mock database responses
    cursor.fetchall.return_value = [
        {
            "id": "test_response_1",
            "studentId": "test_student_1",
            "quizId": "test_quiz_1",
            "score": 0,
            "submittedAt": "2025-01-07 10:25:44.442000",
            "responses": {},
            "violations": "",
            "totalScore": 10.0,
        }
    ]

    # Mock database operations
    cursor.execute.return_value = None
    conn.commit.return_value = None
    conn.close.return_value = None
    cursor.close.return_value = None

    return cursor, conn


@pytest.fixture
def mongo_mock():
    mongo_db = MagicMock()
    mongo_db["NEW_QUESTIONS"].find.return_value = [
        {
            "_id": "test_question_1",
            "quizId": "test_quiz_1",
            "type": "MCQ",
            "question": "Test Question",
            "mark": 10,
            "answer": ["A"],
        }
    ]
    # Mock database cleanup
    mongo_db.close.return_value = None
    return mongo_db


def test_quiz_lock_acquire(redis_mock):
    """Test lock acquisition"""
    lock = QuizLock(redis_mock, "test_quiz_1")
    assert lock.acquire() is True
    redis_mock.set.assert_called_once_with(
        "quiz_lock:test_quiz_1", "locked", nx=True, ex=3600
    )


def test_quiz_lock_release(redis_mock):
    """Test lock release"""
    lock = QuizLock(redis_mock, "test_quiz_1")
    assert lock.release() is True
    redis_mock.delete.assert_called_once_with("quiz_lock:test_quiz_1")


def test_quiz_lock_is_locked(redis_mock):
    """Test lock status check"""
    lock = QuizLock(redis_mock, "test_quiz_1")

    # Test when not locked
    redis_mock.exists.return_value = 0
    assert lock.is_locked() is False

    # Test when locked
    redis_mock.exists.return_value = 1
    assert lock.is_locked() is True


def test_quiz_lock_get_ttl(redis_mock):
    """Test getting lock TTL"""
    lock = QuizLock(redis_mock, "test_quiz_1")
    assert lock.get_lock_ttl() == 3600
    redis_mock.ttl.assert_called_once_with("quiz_lock:test_quiz_1")


def test_quiz_lock_context_manager(redis_mock):
    """Test lock usage as context manager"""
    with QuizLock(redis_mock, "test_quiz_1") as lock:
        assert isinstance(lock, QuizLock)
        redis_mock.set.assert_called_once()
    redis_mock.delete.assert_called_once()


def test_quiz_lock_non_blocking(redis_mock):
    """Test non-blocking lock acquisition"""
    lock = QuizLock(redis_mock, "test_quiz_1")

    # Simulate lock already exists
    redis_mock.set.return_value = False
    assert lock.acquire(blocking=False) is False


@pytest.mark.asyncio
async def test_evaluation_job_with_lock(redis_mock, postgres_mock, mongo_mock):
    """Test evaluation job with lock handling"""
    with (
        patch("utils.redisQueue.job.get_redis_client", return_value=redis_mock),
        patch("utils.redisQueue.job.get_postgres_cursor", return_value=postgres_mock),
        patch("utils.redisQueue.job.get_mongo_client", return_value=mongo_mock),
        patch("utils.redisQueue.job.bulk_evaluate_quiz_responses") as mock_evaluate,
    ):
        mock_evaluate.return_value = {
            "status": "success",
            "message": "Test evaluation complete",
        }
        quiz_id = "test_quiz_1"

        # Test when quiz is not locked
        redis_mock.set.return_value = True  # Lock can be acquired
        result = await evaluation_job(
            quiz_id=quiz_id,
            model_provider=LLMProvider.GROQ,
            model_name="test-model",
            model_api_key="test-key",
        )
        assert result["status"] == "success"

        # Test when quiz is already locked
        redis_mock.set.return_value = False  # Lock cannot be acquired
        redis_mock.ttl.return_value = 1800  # 30 minutes remaining
        result = await evaluation_job(
            quiz_id=quiz_id,
            model_provider=LLMProvider.GROQ,
            model_name="test-model",
            model_api_key="test-key",
        )
        assert result["status"] == "locked"
        assert result["remaining_time"] == 1800


@pytest.mark.asyncio
async def test_concurrent_lock_acquisition(redis_mock):
    """Test concurrent lock acquisition attempts"""
    lock1 = QuizLock(redis_mock, "test_quiz_1")
    lock2 = QuizLock(redis_mock, "test_quiz_1")

    # First lock succeeds
    redis_mock.set.side_effect = [True, False]
    assert lock1.acquire(blocking=False) is True

    # Second lock fails
    assert lock2.acquire(blocking=False) is False


@pytest.mark.asyncio
async def test_lock_timeout(redis_mock):
    """Test lock timeout behavior"""
    lock = QuizLock(redis_mock, "test_quiz_1", timeout=1)

    # Simulate lock acquisition
    redis_mock.set.return_value = True
    assert lock.acquire() is True

    # Verify timeout was set correctly
    redis_mock.set.assert_called_once_with(
        "quiz_lock:test_quiz_1", "locked", nx=True, ex=1
    )


@pytest.mark.asyncio
async def test_lock_release_on_error(redis_mock, postgres_mock, mongo_mock):
    """Test lock release when evaluation job raises an error"""
    with (
        patch("utils.redisQueue.job.get_redis_client", return_value=redis_mock),
        patch("utils.redisQueue.job.get_postgres_cursor", return_value=postgres_mock),
        patch("utils.redisQueue.job.get_mongo_client", return_value=mongo_mock),
        patch("utils.redisQueue.job.bulk_evaluate_quiz_responses") as mock_evaluate,
        patch("utils.redisQueue.job.get_llm") as mock_llm,
    ):
        # Setup mock to simulate error in evaluation
        mock_evaluate.side_effect = Exception("Evaluation failed")
        mock_llm.return_value = MagicMock()

        quiz_id = "test_quiz_1"
        pg_cursor, pg_conn = postgres_mock

        # Test the evaluation job
        result = await evaluation_job(
            quiz_id=quiz_id,
            model_provider=LLMProvider.GROQ,
            model_name="test-model",
            model_api_key="test-key",
        )

        # Verify lock was acquired and released
        redis_mock.set.assert_called_once_with(
            f"quiz_lock:{quiz_id}", "locked", nx=True, ex=3600
        )
        redis_mock.delete.assert_called_once_with(f"quiz_lock:{quiz_id}")

        # Verify database connections were properly closed
        pg_cursor.close.assert_called_once()
        pg_conn.close.assert_called_once()

        # Verify error handling
        assert result["status"] == "failed"
        assert "Evaluation failed" in result.get("details", "")

        # Verify no lingering transactions
        pg_conn.commit.assert_not_called()  # Should not commit on error


@pytest.mark.asyncio
async def test_multiple_quiz_locks(redis_mock):
    """Test handling multiple quiz locks simultaneously"""
    locks = {}
    quiz_ids = ["quiz_1", "quiz_2", "quiz_3"]

    # Set up different return values for different quiz IDs
    redis_mock.set.side_effect = [True, True, False]

    for quiz_id in quiz_ids:
        locks[quiz_id] = QuizLock(redis_mock, quiz_id)
        await asyncio.sleep(0.1)  # Simulate slight delay between requests
