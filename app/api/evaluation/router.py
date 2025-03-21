import json
import uuid
import deprecated
from app.core.logger import logger
from fastapi import APIRouter, Depends, HTTPException

from .models import EvalRequest, ReEvalRequest
from .utils.lock import QuizLock

from app.api.evaluation.service import (
    bulk_evaluate_quiz_responses,
    get_quiz_responses,
    get_all_questions,
    generate_quiz_report,
    save_quiz_report,
)
from app.core.exceptions import InvalidQuizIDError
from app.database.mongo import get_mongo_client
from app.database.postgres import get_postgres_cursor
from app.database.redis import get_redis_client
from app.api.evaluation.utils.evaluation_job import evaluation_job
from app.config.constants import WORKER_TTL
from app.core.dependencies import get_llm_dependency, get_app
from app.api.workers.service import get_quiz_status_from_queue
from app.api.evaluation.utils.db_api import get_quiz_isevaluated
from app.utils.wakeup_workers import get_running_quiz_ids

# Router
router = APIRouter(prefix="/evaluation", tags=["Evaluation"])


@deprecated.deprecated(reason="Use /evaluate instead")
@router.post("/evaluate-wo-queue")
async def evaluate_bulk(request: EvalRequest, llm=Depends(get_llm_dependency)):
    postgres_cursor, postgres_conn = get_postgres_cursor()
    mongo_db = get_mongo_client()
    redis_client = get_redis_client()
    try:
        results = await bulk_evaluate_quiz_responses(
            request.quiz_id,
            postgres_cursor,
            postgres_conn,
            mongo_db,
            redis_client,
            save_to_file=True,
            llm=llm,
        )
        return {"message": "Evaluation complete", "results": results}
    except InvalidQuizIDError as e:
        logger.error(f"Invalid quiz ID error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.error("Error during evaluation", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        postgres_cursor.close()
        postgres_conn.close()


@router.get("/status/{quiz_id}")
async def get_evaluation_status(
    quiz_id: str, redis_client=Depends(get_redis_client), app=Depends(get_app)
):
    """
    Retrieve the evaluation progress status for a given quiz.

    Args:
        quiz_id (str): Identifier of the quiz.
        redis_client: A Redis client dependency for accessing cached progress data.

    Returns:
        dict: A dictionary containing the quiz_id and either the progress details or a message.

    Status Codes:
        200: Evaluation in progress, returns progress details.
        303: No evaluation is running for the quiz.
        500: Error decoding progress data.
    """
    logger.info(f"Checking evaluation status for quiz_id: {quiz_id}")
    try:
        # For EVALUATING - Check Worker
        if quiz_id in get_running_quiz_ids():
            quiz_queue_status = "EVALUATING"

        else:  # If not in job registeries (failed, completed, queued)
            # For QUEUED, FAILED, COMPLETED
            quiz_queue_status = get_quiz_status_from_queue(
                app.state.task_queue, quiz_id
            )  # Can be none
            if quiz_queue_status:
                quiz_queue_status = quiz_queue_status.get(
                    "queue_status", "UNKNOWN"
                ).upper()  # queued, failed, completed

            else:
                # For EVALUATED, UNEVALUATED
                cursor, _ = get_postgres_cursor()
                quiz_queue_status = get_quiz_isevaluated(cursor, quiz_id)
                cursor.close()

            if quiz_queue_status is None:
                quiz_queue_status = "UNKNOWN"
    except Exception as e:
        logger.error(
            f"Unexpected error while checking status for quiz {quiz_id}: {str(e)}",
            exc_info=True,
        )
        return {
            "quiz_id": quiz_id,
            "message": "Unexpected error",
            "status": 500,
        }

    progress = redis_client.get(f"quiz_progress:{quiz_id}")
    if progress:
        try:
            progress = json.loads(progress)
        except json.JSONDecodeError as e:
            logger.error(
                f"Error decoding JSON for quiz {quiz_id} while checking status: {str(e)}"
            )
            return {
                "quiz_id": quiz_id,
                "message": "Invalid progress data",
                "status": 500,
            }

    if quiz_queue_status in [
        "EVALUATED",
        "QUEUED",
        "EVALUATING",
        "COMPLETED",
    ]:
        quiz_queue_status = (
            "COMPLETED" if quiz_queue_status == "EVALUATED" else quiz_queue_status
        )
        return {
            "quiz_id": quiz_id,
            "message": f"Evaluation is {quiz_queue_status}",
            **(progress or {}),
            "status": 200,
            "job_status": quiz_queue_status,
        }
    else:  # value can be ["UNEVALUATED", "FAILED", "UNKNOWN",]
        return {
            "quiz_id": quiz_id,
            "message": "No Evaluation is Running",
            "status": 303,
            "job_status": quiz_queue_status,
        }


@router.post("/evaluate")
async def evaluate_bulk_queue(
    request: EvalRequest,
    app=Depends(get_app),
):
    trace_id = uuid.uuid4()
    logger.info(f"[{trace_id}] Queueing evaluation for quiz_id: {request.quiz_id}")

    try:
        # Check if quiz is already being evaluated
        redis_client = get_redis_client()
        quiz_lock = QuizLock(redis_client, request.quiz_id)
        app.state.quiz_locks[request.quiz_id] = quiz_lock

        if quiz_lock.is_locked():
            remaining_time = quiz_lock.get_lock_ttl()
            if request.override_locked:
                logger.warning(
                    f"[{trace_id}] Quiz {request.quiz_id} is locked with {remaining_time}s remaining. Overriding lock"
                )
                if not quiz_lock.release():
                    logger.warning(
                        f"[{trace_id}] Failed to release lock for quiz {request.quiz_id}"
                    )
            else:
                logger.warning(
                    f"[{trace_id}] Quiz {request.quiz_id} is already being evaluated. Remaining time: {remaining_time}s"
                )
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": f"Quiz {request.quiz_id} is already being evaluated",
                        "remaining_time": remaining_time,
                    },
                )

        task_queue = app.state.task_queue
        job = task_queue.enqueue(
            evaluation_job,
            request.quiz_id,
            app.state.current_provider,
            app.state.current_model_name,
            app.state.current_api_key,
            request.override_evaluated,
            request.types_to_evaluate,
            request.override_cache,
            job_timeout=WORKER_TTL,
        )
        logger.info(
            f"[{trace_id}] Successfully queued evaluation job. Job ID: {job.id}"
        )
        return {"message": "Evaluation queued", "job_id": job.id}
    except HTTPException as e:
        logger.error(f"[{trace_id}] HTTP Exception: {str(e)}")
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception:
        logger.error(f"[{trace_id}] Failed to queue evaluation", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/reevaluate")
async def reevaluate_bulk_queue(
    request: ReEvalRequest,
    app=Depends(get_app),
):
    trace_id = uuid.uuid4()
    logger.info(f"[{trace_id}] Queueing reevaluation for quiz_id: {request.quiz_id}")

    try:
        # Get database connections
        postgres_cursor, postgres_conn = get_postgres_cursor()

        try:
            # Reset evaluation status for specified student IDs
            placeholders = ",".join(["%s"] * len(request.student_ids))
            update_query = f"""
            UPDATE "QuizResult"
            SET "isEvaluated" = 'UNEVALUATED'
            WHERE "quizId" = %s AND "studentId" IN ({placeholders})
            """
            params = [request.quiz_id] + request.student_ids
            postgres_cursor.execute(update_query, params)
            updated_rows = postgres_cursor.rowcount
            postgres_conn.commit()

            logger.info(
                f"[{trace_id}] Reset evaluation status for {updated_rows} quiz results for quiz_id: {request.quiz_id}"
            )

            # Now queue the evaluation job using the same request parameters
            evaluate_request = EvalRequest(
                quiz_id=request.quiz_id,
                override_evaluated=request.override_evaluated,
                override_locked=request.override_locked,
                override_cache=request.override_cache,
                types_to_evaluate=request.types_to_evaluate,
            )

            # Forward to the evaluate endpoint
            return await evaluate_bulk_queue(evaluate_request, app=app)

        except Exception:
            logger.error(f"[{trace_id}] Failed to reevaluate quiz", exc_info=True)
            postgres_conn.rollback()
            raise HTTPException(status_code=500, detail="Failed to reevaluate quiz")

        finally:
            postgres_cursor.close()
            postgres_conn.close()

    except Exception:
        logger.error(f"[{trace_id}] Error setting up reevaluation", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/regenerate-quiz-report/{quiz_id}")
async def regenerate_quiz_report(quiz_id: str):
    postgres_cursor, postgres_conn = get_postgres_cursor()
    mongo_db = get_mongo_client()
    redis_client = get_redis_client()
    logger.info(f"Regenerating quiz report for quiz_id: {quiz_id}")
    try:
        response = get_quiz_responses(postgres_cursor, redis_client, quiz_id)
        questions = get_all_questions(mongo_db, redis_client, quiz_id)
        report = await generate_quiz_report(quiz_id, response, questions)
        await save_quiz_report(
            quiz_id, report, postgres_cursor, postgres_conn, save_to_file=True
        )
        logger.info(f"Quiz report regenerated successfully for quiz_id: {quiz_id}")
        return {"message": "Quiz report regenerated successfully"}
    except InvalidQuizIDError as e:
        logger.error(f"Invalid quiz ID error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.error("Error regenerating quiz report", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        postgres_cursor.close()
        postgres_conn.close()
