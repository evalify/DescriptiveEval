from app.core.logger import logger


def get_queue_info(
    queue,
):
    """
    Get detailed information about the job queue.
    Args:
        queue: The job queue to fetch information from.
    Returns:
            A dictionary containing information about queued, failed, and completed jobs.
    """
    try:
        # Get jobs from different states with error handling
        queued_jobs = queue.get_jobs() or []
        failed_registry = queue.failed_job_registry
        completed_registry = queue.finished_job_registry

        failed_jobs = failed_registry.get_job_ids() if failed_registry else []
        completed_jobs = completed_registry.get_job_ids() if completed_registry else []
        return {
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
            "total": {
                "queued": len(queued_jobs),
                "failed": len(failed_jobs),
                "completed": len(completed_jobs),
            },
        }
    except Exception as e:
        logger.error(f"Error fetching queue information: {str(e)}", exc_info=True)


def get_quiz_status_from_queue(
    queue,
    quiz_id,
) -> dict | None:
    """
    Get detailed information about a specific quiz job in the queue. (queueued, failed, completed)
    Args:
        queue: The job queue to fetch information from.
        quiz_id: The quiz ID to search for in the queue.
    Returns:
            A dictionary containing information about the quiz job.
    """
    try:
        # Search for the quiz_id in queued jobs
        queued_jobs = queue.get_jobs() or []
        for job in queued_jobs:
            if job and job.args and job.args[0] == quiz_id:
                return {
                    "job_id": job.id,
                    "quiz_id": job.args[0] if job.args else None,
                    "enqueued_at": job.enqueued_at.isoformat()
                    if job.enqueued_at
                    else None,
                    "status": job.get_status(),
                    "queue_status": "queued",
                    "worker_pid": job.worker_name.split(".")[1]
                    if job.worker_name
                    else None,
                }

        # Search for the quiz_id in completed jobs
        completed_registry = queue.finished_job_registry
        completed_jobs = completed_registry.get_job_ids() if completed_registry else []
        for job_id in completed_jobs:
            job = queue.fetch_job(job_id)
            if job and job.args and job.args[0] == quiz_id:
                return {
                    "job_id": job_id,
                    "quiz_id": job.args[0] if job.args else None,
                    "completed_at": job.ended_at.isoformat() if job.ended_at else None,
                    "queue_status": "completed",
                    "duration": (job.ended_at - job.started_at).total_seconds()
                    if job and job.ended_at and job.started_at
                    else None,
                }

        # Search for the quiz_id in failed jobs
        failed_registry = queue.failed_job_registry
        failed_jobs = failed_registry.get_job_ids() if failed_registry else []
        for job_id in failed_jobs:
            job = queue.fetch_job(job_id)
            if job and job.args and job.args[0] == quiz_id:
                return {
                    "job_id": job_id,
                    "quiz_id": job.args[0] if job.args else None,
                    "failed_at": job.ended_at.isoformat() if job.ended_at else None,
                    "error_message": job.exc_info if job else None,
                    "queue_status": "failed",
                }

        return None  # Quiz not found in any queue

    except Exception as e:
        logger.error(
            f"Error fetching quiz information from queue: {str(e)}", exc_info=True
        )
        return None
