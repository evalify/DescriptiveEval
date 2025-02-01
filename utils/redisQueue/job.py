from utils.database import get_postgres_cursor, get_mongo_client, get_redis_client
from model import get_llm
from evaluation import bulk_evaluate_quiz_responses
from utils.errors import *
from utils.logger import logger
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

async def evaluation_job(quiz_id: str, model_provider, model_name, model_api_key, override_evaluated=False):
    """Execute the evaluation job for the given quiz ID."""
    job_id = f"eval_{quiz_id}_{model_name}"
    logger.info(f"Starting evaluation job {job_id}")
    
    pg_cursor = pg_conn = None
    
    try:
        # Initialize connections
        pg_cursor, pg_conn = get_postgres_cursor()
        mongo_db = get_mongo_client()
        redis_client = get_redis_client()
        logger.info(f"Job {job_id}: Connections established")
        
        llm = None
        if model_name is not None:
            llm = get_llm(provider=model_provider, model_name=model_name, api_key=model_api_key)
        
        async def execute_evaluation():
            result = await bulk_evaluate_quiz_responses(
                quiz_id, pg_cursor, pg_conn, mongo_db, redis_client,
                save_to_file=True, llm=llm, override_evaluated=override_evaluated
            )
            return {"status": "success", "message": "Evaluation complete", "results": result}
            
        return await handle_evaluation(job_id, execute_evaluation)
        
    finally:
        if pg_cursor and pg_conn:
            try:
                pg_cursor.close()
                pg_conn.close()
                logger.info(f"Job {job_id}: Connections closed")
            except Exception as e:
                logger.error(f"Job {job_id}: Failed to close connections: {str(e)}")