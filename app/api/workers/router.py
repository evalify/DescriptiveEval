from fastapi import APIRouter, HTTPException, Request, Depends
from rq import Worker, Queue
from rq.command import send_stop_job_command
from app.core.logger import logger
from app.api.evaluation.utils.lock import QuizLock
from app.database.redis import get_redis_client
from app.utils.wakeup_workers import spawn_workers, check_workers
from app.core.dependencies import get_app
import psutil
import uuid

# Router
router = APIRouter(prefix="/workers", tags=["Workers"])


@router.get("/status")
async def get_workers_status(app=Depends(get_app)):
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


@router.post("/jobs/stop/{quiz_id}")
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

        # Unlock the quiz
        quiz_lock = QuizLock(redis_conn, quiz_id)
        if quiz_lock.is_locked():
            quiz_lock.release()
            logger.warning(f"Quiz {quiz_id} lock released")

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


@router.post("/kill/{pid}")
async def kill_worker(pid: int, request: Request, app=Depends(get_app)):
    """Force quit a specific worker process by PID with optional replacement."""
    trace_id = uuid.uuid4()
    logger.info(f"[{trace_id}] Attempting to kill worker with PID: {pid}")

    # Extract parameters from request body
    spawn_replacement = request.get("spawn_replacement", True)
    kill_mode = request.get("mode", "immediate")  # TODO: Implement graceful kill

    logger.info(
        f"[{trace_id}] Kill mode: {kill_mode}, Spawn replacement: {spawn_replacement}"
    )

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
                quiz_id = current_job.args[0] if current_job.args else None
                logger.warning(
                    f"[{trace_id}] Cancelling job {current_job.id} on worker {pid}"
                )
                send_stop_job_command(redis_conn, current_job.id)
                current_job.cancel()
                current_job.save()
                if quiz_id:
                    # Unlock the quiz
                    quiz_lock = QuizLock(redis_conn, quiz_id)
                    if quiz_lock.is_locked():
                        quiz_lock.release()
                        logger.warning(f"Quiz {quiz_id} lock released")

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
