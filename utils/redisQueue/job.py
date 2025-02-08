from utils.database import get_postgres_cursor, get_mongo_client, get_redis_client
from model import get_llm
from evaluation import bulk_evaluate_quiz_responses
from utils.errors import *
from utils.logger import logger, QuizLogger
from utils.redisQueue.lock import QuizLock
from functools import wraps
import asyncio

# Group errors by category for cleaner handling
EVALUATION_ERRORS = {
    # Configuration errors
    NoQuestionsError: ("Quiz Configuration Error", "No questions configured"),
    InvalidQuestionError: ("Question Configuration Error", "Invalid question setup"),
    TotalScoreError: ("Score Configuration Error", "Score inconsistency"),
    
    # Submission errors
    NoResponsesError: ("No Submissions", "No student submissions found"),
    
    # Processing errors
    LLMEvaluationError: ("LLM Evaluation Error", "LLM evaluation failed"),
    MCQEvaluationError: ("MCQ Evaluation Error", "MCQ evaluation failed"),
    TrueFalseEvaluationError: ("True/False Evaluation Error", "True/False evaluation failed"),
    CodingEvaluationError: ("Coding Evaluation Error", "Code evaluation failed"),
    FillInBlankEvaluationError: ("Fill in Blank Error", "Fill in blank evaluation failed"),
    
    # System errors
    DatabaseConnectionError: ("Database Error", "Database operation failed"),
    EvaluationError: ("Evaluation Error", "General evaluation error")
}

async def handle_evaluation(job_id: str, func):
    """Wrapper for handling evaluation functions with proper error handling"""
    try:
        if not asyncio.iscoroutinefunction(func):
            raise TypeError("The provided function is not a coroutine function")
        return await func()
    except tuple(EVALUATION_ERRORS.keys()) as e:
        error_title, _ = EVALUATION_ERRORS[type(e)]
        logger.error(f"Job {job_id}: {error_title}", exc_info=True)
        return {
            "status": "failed",
            "error": error_title,
            "details": str(e)
        }
    except Exception as e:
        logger.critical(f"Job {job_id}: Critical error", exc_info=True)
        return {
            "status": "failed",
            "error": "Critical Error",
            "details": f"An unexpected error occurred: {str(e)}"
        }

async def evaluation_job(quiz_id: str, model_provider, model_name, model_api_key, override_evaluated=False, types_to_evaluate=None):
    """Execute the evaluation job for the given quiz ID."""
    job_id = f"eval_{quiz_id}_{model_name}"
    qlogger = QuizLogger(quiz_id)
    qlogger.info(f"Starting evaluation job {job_id}")
    qlogger.debug(f"Job parameters: provider={model_provider}, model={model_name}, override={override_evaluated}, types={types_to_evaluate}")
    
    pg_cursor = pg_conn = None
    redis_client = get_redis_client()
    
    # Create a lock for this quiz
    quiz_lock = QuizLock(redis_client, quiz_id)
    
    try:
        # Try to acquire the lock (non-blocking)
        if not quiz_lock.acquire(blocking=False):
            remaining_time = quiz_lock.get_lock_ttl()
            qlogger.warning(f"Quiz {quiz_id} is already being evaluated. Remaining time: {remaining_time}s")
            return {
                "status": "locked",
                "message": f"Quiz {quiz_id} is already being evaluated",
                "remaining_time": remaining_time
            }
    
        # Initialize connections
        pg_cursor, pg_conn = get_postgres_cursor()
        mongo_db = get_mongo_client()
        qlogger.debug(f"Database connections established for job {job_id}")
        
        llm = None
        if model_name is not None:
            llm = get_llm(provider=model_provider, model_name=model_name, api_key=model_api_key)
            qlogger.debug(f"Initialized LLM model {model_name} for job {job_id}")
        
        async def execute_evaluation():
            result = await bulk_evaluate_quiz_responses(
                quiz_id, pg_cursor, pg_conn, mongo_db, redis_client,
                save_to_file=True, llm=llm, override_evaluated=override_evaluated,
                types_to_evaluate=types_to_evaluate
            )
            return {"status": "success", "message": "Evaluation complete", "results": result}
            
        result = await handle_evaluation(job_id, execute_evaluation)
        if result["status"] == "success":
            qlogger.info(f"Job {job_id} completed successfully")
        else:
            qlogger.error(f"Job {job_id} failed: {result['error']} - {result['details']}")
        return result
        
    finally:
        # Release the lock in finally block to ensure it's released even if an error occurs
        quiz_lock.release()
        
        if pg_cursor and pg_conn:
            try:
                pg_cursor.close()
                pg_conn.close()
                qlogger.debug(f"Database connections closed for job {job_id}")
            except Exception as e:
                qlogger.error(f"Failed to close database connections for job {job_id}: {str(e)}")
                logger.error(f"Job {job_id}: Failed to close database connections")