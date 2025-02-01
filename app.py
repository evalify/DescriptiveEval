import os
import time
import uuid
from typing import Optional

import deprecated
import psutil
from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from rq import Queue, Worker

from evaluation import bulk_evaluate_quiz_responses
from model import LLMProvider, get_llm, score, generate_guidelines, enhance_question_and_answer
from utils.database import get_postgres_cursor, get_mongo_client, get_redis_client
from utils.logger import logger
from utils.redisQueue import job as rq_job
from utils.redisQueue.wakeup_workers import spawn_workers, check_workers

app = FastAPI()
logger.info("Initializing FastAPI application")

# Initialize workers when app starts
worker_processes = spawn_workers()
logger.info(f"Initialized {len(worker_processes)} worker processes")

# Store current provider in app state
app.state.current_provider = LLMProvider.OLLAMA
app.state.current_model_name = "deepseek-r1:32b"
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
    types_to_evaluate: Optional[dict] = {
            'MCQ': True,
            'DESCRIPTIVE': True,
            'CODING': True,
            'TRUE_FALSE': True,
            'FILL_IN_BLANK': True
        }


@app.get("/")
async def read_index():
    return FileResponse('static/index.html')


def get_llm_dependency():
    """Dependency to provide LLM instance based on current provider"""
    return get_llm(provider=app.state.current_provider, model_name=app.state.current_model_name,
                   api_key=app.state.current_api_key)


def get_micro_llm_dependency():
    return get_llm(provider=app.state.current_micro_llm_provider, model_name=app.state.current_micro_llm_model_name,
                   api_key=app.state.current_micro_llm_api_key)


@app.post("/set-provider")
async def change_provider(request: ProviderRequest):
    try:
        provider = LLMProvider(request.provider.lower())
        provider_model_name = request.provider_model_name
        provider_api_key = request.provider_api_key

        if request.service == "macro":
            logger.info(f"Changing provider to {provider.value} with model {provider_model_name}")
            app.state.current_provider = provider
            app.state.current_model_name = provider_model_name
            app.state.current_api_key = provider_api_key
        elif request.service == "micro":
            logger.info(f"Changing micro provider to {provider.value} with model {provider_model_name}")
            app.state.current_micro_llm_provider = provider
            app.state.current_micro_llm_model_name = provider_model_name
            app.state.current_micro_llm_api_key = provider_api_key
        else:
            raise ValueError(f"Invalid service type : {request.service}")

        return {"message": f"Successfully switched to {provider.value} provider with model {provider_model_name}"}
    except ValueError as e:
        logger.error(f"Error changing provider: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/score")
async def get_response(
        request: QueryRequest,
        llm=Depends(get_llm_dependency)
):
    trace_id = uuid.uuid4()
    logger.info(f"[{trace_id}] Scoring request received for question: {request.question[:100]}...")

    try:
        result = await score(
            llm=llm,
            student_ans=request.student_ans,
            expected_ans=request.expected_ans,
            total_score=request.total_score,
            question=request.question,
            guidelines=request.guidelines  # Pass guidelines if provided
        )
        logger.info(f"[{trace_id}] Scoring complete. Score: {result.get('score')}")
        return result
    except Exception as e:
        logger.error(f"[{trace_id}] Error processing scoring request", exc_info=True)
        raise


@app.post("/generate-guidelines")
async def generate_guidelines_api(
        request: GuidelinesRequest,
        llm=Depends(get_micro_llm_dependency)
):
    trace_id = uuid.uuid4()
    logger.info(f"[{trace_id}] Guidelines generation request received for question: {request.question[:100]}...")

    try:
        guidelines_result = await generate_guidelines(
            llm,
            question=request.question or "",
            expected_ans=request.expected_ans or "",
            total_score=request.total_score or 10
        )
        logger.info(f"[{trace_id}] Guidelines generated successfully")
        return guidelines_result
    except Exception as e:
        logger.error(f"[{trace_id}] Error generating guidelines", exc_info=True)
        raise


@app.post("/enhance-qa")
async def enhance_qa(
        request: QAEnhancementRequest,
        llm=Depends(get_micro_llm_dependency)
):
    result = await enhance_question_and_answer(
        llm,
        question=request.question,
        expected_ans=request.expected_ans
    )
    return result


@deprecated.deprecated(reason="Use /evaluate instead")
@app.post("/evaluate-wo-queue")  # TODO: Implement Queueing
async def evaluate_bulk(
        request: EvalRequest,
        llm=Depends(get_llm_dependency)
):
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
            llm=llm
        )
        return {"message": "Evaluation complete", "results": results}  # TODO: Give more detailed response
    finally:
        postgres_cursor.close()
        postgres_conn.close()


@app.get("/queued-quizzes") 
async def get_queued_quizzes():
    """Get all currently queued quiz evaluation jobs."""
    trace_id = uuid.uuid4()
    logger.info(f"[{trace_id}] Fetching queued quiz evaluations")
    
    try:
        queued_jobs = tasks_queue.get_jobs()
        queued_quizzes = []
        for job in queued_jobs:
            quiz_id = job.args[0] if job.args else None
            queued_quizzes.append({
                "job_id": job.id,
                "quiz_id": quiz_id,
                "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
                "status": job.get_status()
            })
        
        logger.info(f"[{trace_id}] Found {len(queued_quizzes)} queued quiz evaluations")
        return {"queued_quizzes": queued_quizzes}
        
    except Exception as e:
        logger.error(f"[{trace_id}] Error fetching queued quizzes", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch queued quizzes: {str(e)}"
        )


@app.post("/evaluate")
async def evaluate_bulk_queue(
        request: EvalRequest,
):
    trace_id = uuid.uuid4()
    logger.info(f"[{trace_id}] Queueing evaluation for quiz_id: {request.quiz_id}")

    try:
        job = tasks_queue.enqueue(
            rq_job.evaluation_job,
            request.quiz_id,
            app.state.current_provider,
            app.state.current_model_name,
            app.state.current_api_key,
            request.override_evaluated,
            request.types_to_evaluate,
            job_timeout=int(os.getenv('WORKER_TTL', '3600'))
        )
        logger.info(f"[{trace_id}] Successfully queued evaluation job. Job ID: {job.id}")
        return {"message": "Evaluation queued", "job_id": job.id}
    except Exception as e:
        logger.error(f"[{trace_id}] Failed to queue evaluation", exc_info=True)
        raise


@app.get("/workers/status")
async def get_workers_status():
    """Get the status of all worker processes"""
    trace_id = uuid.uuid4()
    logger.debug(f"[{trace_id}] Checking worker status")
    try:
        status = check_workers(worker_processes)  # Direct call, not async
        active_workers = sum(1 for w in status if w['status'] == 'running')
        logger.info(f"[{trace_id}] Worker status check complete. {active_workers} active workers")
        return status
    except Exception as e:
        logger.error(f"[{trace_id}] Error checking worker status", exc_info=True)
        raise


@app.post("/workers/kill/{pid}")
async def kill_worker(pid: int):
    """Force quit a specific worker process by PID."""
    trace_id = uuid.uuid4()
    logger.info(f"[{trace_id}] Attempting to kill worker with PID: {pid}")

    try:
        # Verify the PID belongs to one of our workers
        worker_pids = [p.pid for p in worker_processes]
        if pid not in worker_pids:
            raise HTTPException(
                status_code=404,
                detail=f"No worker found with PID {pid}"
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
                logger.warning(f"[{trace_id}] Cancelling job {current_job.id} on worker {pid}")
                current_job.cancel()
                current_job.save()

            # Deregister the worker
            worker.register_death()
            logger.info(f"[{trace_id}] Deregistered worker {pid} from Redis")

        # Verify it's actually our worker python process
        if not process.name().lower().startswith('python'):
            raise HTTPException(
                status_code=400,
                detail=f"Process {pid} is not a Python worker process"
            )

        # Kill the process and its children
        children = process.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass

        # Try graceful termination first
        process.terminate()

        try:
            process.wait(timeout=3)  # Reduced timeout since we're being more aggressive
        except psutil.TimeoutExpired:
            logger.warning(f"[{trace_id}] Worker {pid} did not terminate gracefully, forcing kill")
            process.kill()

        # Ensure the process is dead
        max_wait = 5
        start_time = time.time()
        while time.time() - start_time < max_wait:
            if not psutil.pid_exists(pid):
                break
            time.sleep(0.1)
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to terminate worker {pid} after {max_wait} seconds"
            )

        logger.info(f"[{trace_id}] Successfully terminated worker {pid}")

        # Get updated worker status
        time.sleep(0.5)  # Short delay to let system update
        status_info = check_workers(worker_processes)  # Direct call, not async

        return {
            "message": f"Worker {pid} terminated successfully",
            "workers": status_info
        }

    except psutil.NoSuchProcess:
        logger.error(f"[{trace_id}] Worker {pid} not found")
        raise HTTPException(
            status_code=404,
            detail=f"Worker process {pid} not found"
        )
    except psutil.AccessDenied:
        logger.error(f"[{trace_id}] Access denied when trying to kill worker {pid}")
        raise HTTPException(
            status_code=403,
            detail=f"Access denied when trying to kill worker {pid}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{trace_id}] Error killing worker {pid}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to kill worker {pid}: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=4040)
