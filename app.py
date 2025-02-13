import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import deprecated
import psutil
from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from rq import Queue, Worker
from rq.job import JobStatus
from rq.command import send_stop_job_command

from evaluation import (
    bulk_evaluate_quiz_responses,
    get_quiz_responses,
    get_all_questions,
)
from model import (
    LLMProvider,
    get_llm,
    score,
    generate_guidelines,
    enhance_question_and_answer,
)
from utils.database import get_postgres_cursor, get_mongo_client, get_redis_client
from utils.errors import InvalidInputError, EmptyAnswerError, InvalidQuizIDError
from utils.logger import logger
from utils.quiz.quiz_report import generate_quiz_report, save_quiz_report
from utils.redisQueue import job as rq_job
from utils.redisQueue.lock import QuizLock
from utils.redisQueue.wakeup_workers import spawn_workers, check_workers


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_conn = get_redis_client()

    # Startup: Initialize workers
    try:
        # Initialize quiz locks
        app.state.quiz_locks = {}

        # Check if we're in test environment
        is_test = bool(os.getenv("PYTEST_CURRENT_TEST"))

        if not is_test:
            # Clean up any stale workers first
            stale_workers = Worker.all(connection=redis_conn)
            for w in stale_workers:
                try:
                    worker_pid = (
                        int(w.name.split(".")[1])
                        if len(w.name.split(".")) > 1
                        else None
                    )
                    if worker_pid and not psutil.pid_exists(worker_pid):
                        # Get current job before cleanup
                        current_job = w.get_current_job()
                        if current_job and not current_job.is_finished:
                            # Requeue the job
                            current_job.set_status(JobStatus.QUEUED)
                            current_job.worker_name = None
                            current_job.save()
                        w.teardown()
                        logger.info(f"Cleaned up stale worker {w.name}")
                except (IndexError, ValueError, psutil.NoSuchProcess):
                    continue

            app.state.worker_processes = spawn_workers()

            # Verify workers registered correctly
            timeout = time.time() + 30  # 30 seconds timeout
            while time.time() < timeout:
                registered_workers = Worker.all(connection=redis_conn)
                registered_pids = {
                    int(w.name.split(".")[1])
                    for w in registered_workers
                    if len(w.name.split(".")) > 1 and w.name.split(".")[1].isdigit()
                }
                spawned_pids = {p.pid for p in app.state.worker_processes}

                if registered_pids >= spawned_pids:
                    break
                await asyncio.sleep(1)

            logger.info(
                f"Initialized {len(app.state.worker_processes)} worker processes during startup"
            )
        else:
            # In test environment, use mock workers from app state if they exist
            app.state.worker_processes = getattr(app.state, "worker_processes", [])
            if len(app.state.worker_processes) < 1:
                app.state.worker_processes = spawn_workers()
                await asyncio.sleep(5)  # Wait for workers to start asynchronously
            logger.info(
                f"Test environment: Initialized {len(app.state.worker_processes)} mock workers"
            )
            logger.info(
                f"Test environment: Using {len(app.state.worker_processes)} mock workers"
            )

        # Add Redis queue to app state for easy access
        app.state.task_queue = Queue("task_queue", connection=redis_conn)

    except Exception as e:
        logger.critical("Failed to initialize workers during startup", exc_info=True)
        app.state.worker_processes = []
        app.state.task_queue = Queue("task_queue", connection=redis_conn)

    yield

    # Shutdown: Cleanup workers
    logger.info("Application shutdown: Cleaning up workers...")

    # Get all active jobs first
    active_jobs = {}
    for process in app.state.worker_processes:
        try:
            workers = Worker.all(connection=redis_conn)
            worker = next((w for w in workers if str(process.pid) in w.name), None)
            if worker:
                current_job = worker.get_current_job()
                if current_job:
                    active_jobs[worker.name] = current_job
        except Exception as e:
            logger.error(f"Error getting job for worker {process.pid}: {str(e)}")

    # Now clean up workers
    for process in app.state.worker_processes:
        try:
            # Get the worker from Redis
            workers = Worker.all(connection=redis_conn)
            worker = next((w for w in workers if str(process.pid) in w.name), None)

            if worker:
                # Handle any current job
                if worker.name in active_jobs:
                    current_job = active_jobs[worker.name]
                    if not current_job.is_finished:
                        logger.warning(
                            f"Cancelling job {current_job.id} on worker {process.pid}"
                        )
                        try:
                            # Cancel job state
                            try:
                                send_stop_job_command(redis_conn, current_job.id)
                            except Exception as e:
                                logger.error(
                                    f"Failed to send stop job command for job {current_job.id}: {str(e)}"
                                )
                            else:
                                logger.info(
                                    f"Cancelled job {current_job.id} on worker {process.pid}"
                                )
                                # Uncomment the following block to requeue the job on shutdown
                                # Reset job state
                                # current_job.set_status(JobStatus.QUEUED)
                                # current_job.worker_name = None
                                # current_job.ended_at = None
                                # current_job.save()
                                # # Requeue the job
                                # app.state.task_queue.enqueue_job(current_job)
                                # logger.info(f"Re-queued job {current_job.id}")
                        except Exception as e:
                            logger.error(
                                f"Error handling job {current_job.id} during shutdown: {str(e)}"
                            )

                # Deregister the worker first to prevent new jobs
                worker.teardown()
                logger.info(f"Deregistered worker {process.pid} from Redis")

            if not os.getenv(
                "PYTEST_CURRENT_TEST"
            ):  # Skip process termination in tests
                # Terminate the process
                try:
                    if psutil.pid_exists(process.pid):
                        proc = psutil.Process(process.pid)
                        if proc.is_running():
                            proc.terminate()
                            try:
                                proc.wait(timeout=3)
                            except psutil.TimeoutExpired:
                                proc.kill()
                                proc.wait(timeout=2)
                    logger.info(f"Successfully terminated worker {process.pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.warning(
                        f"Process {process.pid} already terminated: {str(e)}"
                    )
                except Exception as e:
                    logger.error(f"Error terminating process {process.pid}: {str(e)}")
                    # Try force kill as last resort
                    try:
                        if psutil.pid_exists(process.pid):
                            psutil.Process(process.pid).kill()
                    except Exception:
                        pass

        except Exception as e:
            logger.error(
                f"Error cleaning up worker {process.pid}: {str(e)}", exc_info=True
            )

    app.state.worker_processes.clear()

    # Final verification that all workers are cleaned up from Redis
    try:
        remaining_workers = Worker.all(connection=redis_conn)
        for w in remaining_workers:
            try:
                pid = w.name.split(".")[1] if len(w.name.split(".")) > 1 else None
                if (
                    pid
                    and pid.isdigit()
                    and any(str(pid) in p.name for p in app.state.worker_processes)
                ):
                    # Final check for any jobs before unregistering
                    current_job = w.get_current_job()
                    if current_job and not current_job.is_finished:
                        current_job.set_status(JobStatus.QUEUED)
                        current_job.worker_name = None
                        current_job.ended_at = None
                        current_job.save()
                        app.state.task_queue.enqueue_job(current_job)
                    w.teardown()
            except (IndexError, ValueError):
                continue
    except Exception as e:
        logger.error(f"Error during final worker cleanup: {str(e)}")

    # Unlock any remaining quiz locks
    for quiz_id, quiz_lock in app.state.quiz_locks.items():
        if quiz_lock.is_locked():
            quiz_lock.release()
            logger.warning(f"Quiz {quiz_id} lock released during shutdown")

    logger.info("All workers cleaned up")


# Initialize FastAPI with lifespan manager
app = FastAPI(lifespan=lifespan)
logger.info("Initializing FastAPI application")

# Store current provider in app state
app.state.current_provider = LLMProvider.OLLAMA
app.state.current_model_name = "deepseek-r1:70b"
app.state.current_api_key = None

app.state.current_micro_llm_provider = LLMProvider.GROQ
app.state.current_micro_llm_model_name = "llama-3.3-70b-specdec"
app.state.current_micro_llm_api_key = os.getenv("GROQ_API_KEY")

app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Consider restricting origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

tasks_queue = Queue("task_queue", connection=get_redis_client())


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(
        f"Path: {request.url.path} | "
        f"Method: {request.method} | "
        f"Status: {response.status_code} | "
        f"Duration: {duration:.3f}s"
    )
    return response


class QueryRequest(BaseModel):
    question: str = None
    student_ans: str
    expected_ans: str
    total_score: int
    guidelines: Optional[str] = None  # Added guidelines field


class ProviderRequest(BaseModel):
    provider: str
    provider_model_name: str = None
    provider_api_key: str = None
    service: str = "macro"


class GuidelinesRequest(BaseModel):
    question: str = None
    expected_ans: str = None
    total_score: int = 10


class QAEnhancementRequest(BaseModel):
    question: str
    expected_ans: str


class EvalRequest(BaseModel):
    quiz_id: str
    override_evaluated: bool = False
    override_locked: bool = False
    types_to_evaluate: Optional[dict] = Field(
        default_factory=lambda: {
            "MCQ": True,
            "DESCRIPTIVE": True,
            "CODING": True,
            "TRUE_FALSE": True,
            "FILL_IN_BLANK": True,
        }
    )


@app.get("/")
async def read_index():
    return FileResponse("static/index.html")


def get_llm_dependency():
    """Dependency to provide LLM instance based on current provider"""
    return get_llm(
        provider=app.state.current_provider,
        model_name=app.state.current_model_name,
        api_key=app.state.current_api_key,
    )


def get_micro_llm_dependency():
    return get_llm(
        provider=app.state.current_micro_llm_provider,
        model_name=app.state.current_micro_llm_model_name,
        api_key=app.state.current_micro_llm_api_key,
    )


@app.post("/set-provider")
async def change_provider(request: ProviderRequest):
    try:
        provider = LLMProvider(request.provider.lower())
        provider_model_name = request.provider_model_name
        provider_api_key = request.provider_api_key

        if request.service == "macro":
            logger.info(
                f"Changing provider to {provider.value} with model {provider_model_name}"
            )
            app.state.current_provider = provider
            app.state.current_model_name = provider_model_name
            app.state.current_api_key = provider_api_key
        elif request.service == "micro":
            logger.info(
                f"Changing micro provider to {provider.value} with model {provider_model_name}"
            )
            app.state.current_micro_llm_provider = provider
            app.state.current_micro_llm_model_name = provider_model_name
            app.state.current_micro_llm_api_key = provider_api_key
        else:
            raise ValueError(f"Invalid service type : {request.service}")

        return {
            "message": f"Successfully switched to {provider.value} provider with model {provider_model_name}"
        }
    except ValueError as e:
        logger.error(f"Error changing provider: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/score")
async def get_response(request: QueryRequest, llm=Depends(get_llm_dependency)):
    trace_id = uuid.uuid4()
    logger.info(
        f"[{trace_id}] Scoring request received for question: {request.question[:100]}..."
    )

    try:
        result = await score(
            llm=llm,
            student_ans=request.student_ans,
            expected_ans=request.expected_ans,
            total_score=request.total_score,
            question=request.question,
            guidelines=request.guidelines,  # Pass guidelines if provided
        )
        logger.info(f"[{trace_id}] Scoring complete. Score: {result.get('score')}")
        return result
    except InvalidInputError as e:
        logger.error(f"[{trace_id}] Invalid input error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except EmptyAnswerError as e:
        logger.error(f"[{trace_id}] Empty answer error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[{trace_id}] Error processing scoring request", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/generate-guidelines")
async def generate_guidelines_api(
    request: GuidelinesRequest, llm=Depends(get_micro_llm_dependency)
):
    trace_id = uuid.uuid4()
    logger.info(
        f"[{trace_id}] Guidelines generation request received for question: {request.question[:100]}..."
    )

    try:
        errors = []
        MAX_RETRIES = int(os.getenv("MAX_RETRIES", 10))
        for attempt in range(MAX_RETRIES):
            guidelines_result = await generate_guidelines(
                llm,
                question=request.question or "",
                expected_ans=request.expected_ans or "",
                total_score=request.total_score or 10,
                errors=errors,
            )
            if guidelines_result.get("status") != 200:
                error_msg = guidelines_result.get("error", "Unknown Error")
                logger.warning(
                    f"[{trace_id}] Attempt {attempt + 1}/{MAX_RETRIES}: Failed to generate guidelines for api request {error_msg}"
                )
                errors.append(error_msg)
                continue
            else:
                logger.info(f"[{trace_id}] Guidelines generated successfully")
            break
        return guidelines_result
    except InvalidInputError as e:
        logger.error(f"[{trace_id}] Invalid input error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[{trace_id}] Error generating guidelines", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/enhance-qa")
async def enhance_qa(
    request: QAEnhancementRequest, llm=Depends(get_micro_llm_dependency)
):
    try:
        result = await enhance_question_and_answer(
            llm, question=request.question, expected_ans=request.expected_ans
        )
        return result
    except InvalidInputError as e:
        logger.error(f"Invalid input error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error enhancing question and answer", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@deprecated.deprecated(reason="Use /evaluate instead")
@app.post("/evaluate-wo-queue")
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
    except Exception as e:
        logger.error(f"Error during evaluation", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        postgres_cursor.close()
        postgres_conn.close()


@app.post("/evaluate")
async def evaluate_bulk_queue(
    request: EvalRequest,
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

        job = tasks_queue.enqueue(
            rq_job.evaluation_job,
            request.quiz_id,
            app.state.current_provider,
            app.state.current_model_name,
            app.state.current_api_key,
            request.override_evaluated,
            request.types_to_evaluate,
            job_timeout=int(os.getenv("WORKER_TTL", "3600")),
        )
        logger.info(
            f"[{trace_id}] Successfully queued evaluation job. Job ID: {job.id}"
        )
        return {"message": "Evaluation queued", "job_id": job.id}
    except HTTPException as e:
        logger.error(f"[{trace_id}] HTTP Exception: {str(e)}")
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"[{trace_id}] Failed to queue evaluation", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/regenerate-quiz-report/{quiz_id}")
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
    except Exception as e:
        logger.error(f"Error regenerating quiz report", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        postgres_cursor.close()
        postgres_conn.close()


@app.get("/workers/status")
async def get_workers_status():
    """Get detailed status of all worker processes and queue information"""
    trace_id = uuid.uuid4()
    logger.debug(f"[{trace_id}] Checking worker and queue status")
    try:
        # Get worker status with enhanced monitoring
        status = check_workers(app.state.worker_processes)  # Use workers from app state
        active_workers = sum(1 for w in status if w["status"] == "running")

        # Get queue information
        redis_conn = get_redis_client()
        queue = Queue("task_queue", connection=redis_conn)

        try:
            # Get jobs from different states with error handling
            queued_jobs = queue.get_jobs() or []
            failed_registry = queue.failed_job_registry
            completed_registry = queue.finished_job_registry

            failed_jobs = failed_registry.get_job_ids() if failed_registry else []
            completed_jobs = (
                completed_registry.get_job_ids() if completed_registry else []
            )

            # Process job information with error handling
            queue_info = {
                "queued": [
                    {
                        "job_id": job.id,
                        "quiz_id": job.args[0] if job.args else None,
                        "enqueued_at": job.enqueued_at.isoformat()
                        if job.enqueued_at
                        else None,
                        "status": job.get_status(),
                        "worker_pid": job.worker_name.split(".")[1]
                        if job.worker_name
                        else None,
                    }
                    for job in queued_jobs
                    if job
                ],
                "failed": [
                    {
                        "job_id": job_id,
                        "quiz_id": queue.fetch_job(job_id).args[0]
                        if queue.fetch_job(job_id) and queue.fetch_job(job_id).args
                        else None,
                        "failed_at": queue.fetch_job(job_id).ended_at.isoformat()
                        if queue.fetch_job(job_id) and queue.fetch_job(job_id).ended_at
                        else None,
                        "error_message": queue.fetch_job(job_id).exc_info
                        if queue.fetch_job(job_id)
                        else None,
                    }
                    for job_id in failed_jobs
                    if job_id
                ],
                "completed": [
                    {
                        "job_id": job_id,
                        "quiz_id": queue.fetch_job(job_id).args[0]
                        if queue.fetch_job(job_id) and queue.fetch_job(job_id).args
                        else None,
                        "completed_at": queue.fetch_job(job_id).ended_at.isoformat()
                        if queue.fetch_job(job_id) and queue.fetch_job(job_id).ended_at
                        else None,
                        "duration": (
                            queue.fetch_job(job_id).ended_at
                            - queue.fetch_job(job_id).started_at
                        ).total_seconds()
                        if queue.fetch_job(job_id)
                        and queue.fetch_job(job_id).ended_at
                        and queue.fetch_job(job_id).started_at
                        else None,
                    }
                    for job_id in completed_jobs
                    if job_id
                ],
            }
        except Exception as e:
            logger.error(
                f"[{trace_id}] Error processing queue information: {str(e)}",
                exc_info=True,
            )
            queue_info = {"error": "Failed to process queue information"}

        response = {
            "workers": status,
            "active_workers": active_workers,
            "total_workers": len(app.state.worker_processes),
            "queue_info": queue_info,
            "jobs_summary": {
                "queued": len(queued_jobs),
                "failed": len(failed_jobs),
                "completed": len(completed_jobs),
            },
        }

        logger.info(
            f"[{trace_id}] Status check complete. {active_workers} active workers"
        )
        return response

    except Exception as e:
        logger.error(
            f"[{trace_id}] Error checking worker and queue status", exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Internal server error while checking worker status",
                "error": str(e),
            },
        )


@app.post("/jobs/stop/{quiz_id}")
async def stop_jobs(quiz_id: str):
    """Stop all jobs for a specific quiz ID"""
    trace_id = uuid.uuid4()
    logger.info(f"[{trace_id}] Stopping all jobs for quiz ID: {quiz_id}")

    try:
        redis_conn = get_redis_client()
        workers = Worker.all(connection=redis_conn)
        for worker in workers:
            current_job = worker.get_current_job()
            if current_job and current_job.args and current_job.args[0] == quiz_id:
                logger.info(
                    f"[{trace_id}] Cancelling job {current_job.id} on worker {worker.name}"
                )
                try:
                    send_stop_job_command(redis_conn, current_job.id)
                except Exception as e:
                    logger.error(
                        f"Failed to send stop job command for job {current_job.id}: {str(e)}"
                    )
                finally:
                    current_job.cancel()
                    current_job.save()

        return {"message": f"Stopped all jobs for quiz ID: {quiz_id}"}
    except Exception as e:
        logger.error(
            f"[{trace_id}] Error stopping jobs for quiz ID: {quiz_id}", exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail={
                "message": f"Failed to stop jobs for quiz ID: {quiz_id}",
                "error": str(e),
            },
        )


@app.post("/workers/kill/{pid}")
async def kill_worker(pid: int, spawn_replacement: bool = True):
    """Force quit a specific worker process by PID with optional replacement."""
    trace_id = uuid.uuid4()
    logger.info(f"[{trace_id}] Attempting to kill worker with PID: {pid}")

    try:
        # Verify the PID belongs to one of our workers
        worker_pids = [
            p.pid for p in app.state.worker_processes
        ]  # Use workers from app state
        if pid not in worker_pids:
            raise HTTPException(
                status_code=404, detail=f"No worker found with PID {pid}"
            )

        # Get the process and Redis connection
        process = psutil.Process(pid)
        redis_conn = get_redis_client()

        # Find the worker in Redis
        workers = Worker.all(connection=redis_conn)
        worker = next((w for w in workers if str(pid) in w.name), None)

        if worker:
            # Cancel any current job
            current_job = worker.get_current_job()
            if current_job:
                logger.warning(
                    f"[{trace_id}] Cancelling job {current_job.id} on worker {pid}"
                )
                send_stop_job_command(redis_conn, current_job.id)
                current_job.cancel()
                current_job.save()

            # Deregister the worker
            worker.teardown()
            logger.info(f"[{trace_id}] Deregistered worker {pid} from Redis")
        else:
            logger.warning(f"[{trace_id}] Worker {pid} not found in Redis")

        # Kill the worker process
        if process.is_running():
            process.terminate()  # TODO: Check if Work Horse is terminated!
            try:
                process.wait(timeout=3)
            except psutil.TimeoutExpired:
                process.kill()

        # Remove the process from our list
        app.state.worker_processes[:] = [
            p for p in app.state.worker_processes if p.pid != pid
        ]

        # Spawn replacement worker if requested
        new_worker = None
        if spawn_replacement:
            try:
                new_process = spawn_workers(1)[0]
                app.state.worker_processes.append(new_process)
                new_worker = {"pid": new_process.pid, "status": "spawned"}
                logger.info(
                    f"[{trace_id}] Spawned replacement worker with PID: {new_process.pid}"
                )
            except Exception as e:
                logger.error(
                    f"[{trace_id}] Failed to spawn replacement worker", exc_info=True
                )
                new_worker = {"status": "spawn_failed", "error": str(e)}

        # Get updated status
        status_info = check_workers(app.state.worker_processes)

        return {
            "message": f"Worker {pid} terminated successfully",
            "replacement_worker": new_worker,
            "workers": status_info,
        }

    except Exception as e:
        logger.error(f"[{trace_id}] Error killing worker {pid}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to kill worker {pid}: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=4040)
