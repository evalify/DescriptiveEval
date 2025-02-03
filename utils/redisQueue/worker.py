import os
import sys
import socket
import time
import signal
import asyncio

# Add project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(project_root)
from utils.logger import logger, QuizLogger
from rq import Worker
from utils.database import get_redis_client

def handle_signal(signum, frame):
    """Handle interrupt signals gracefully"""
    logger.warning(f"Worker received signal {signum}. Initiating graceful shutdown...")
    raise SystemExit()

# Register signal handlers
signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

# Create a unique worker name using hostname.pid.timestamp format
hostname = socket.gethostname()
pid = os.getpid()
timestamp = int(time.time())
worker_name = f"{hostname}.{pid}.{timestamp}"

try:
    redis_conn = get_redis_client()
    logger.info(f"Worker {worker_name} initializing with Redis connection")
    
    worker = Worker(['task_queue'], connection=redis_conn, name=worker_name, worker_ttl=int(os.getenv('WORKER_TTL', 3600)))
    logger.info(f"Worker {worker_name} successfully created")
    
    # Set up worker to handle job cancellation and track progress
    def handle_job_failure(job, exc_type, exc_value, traceback):
        if isinstance(exc_value, (SystemExit, KeyboardInterrupt)):
            logger.warning(f"Worker {worker_name}: Job {job.id} cancelled by user")
            return False  # Don't retry the job
            
        quiz_id = job.args[0] if job.args else "unknown"
        qlogger = QuizLogger(quiz_id)
        qlogger.error(f"Job {job.id} failed with error: {exc_type.__name__}: {exc_value}")
        logger.error(f"Worker {worker_name}: Job {job.id} failed", exc_info=True)
        return True  # Retry other types of failures

    def handle_job_success(job, connection, result, *args, **kwargs):
        quiz_id = job.args[0] if job.args else "unknown"
        qlogger = QuizLogger(quiz_id)
        qlogger.info(f"Job {job.id} completed successfully")
        logger.info(f"Worker {worker_name}: Job {job.id} completed")

    worker.push_exc_handler(handle_job_failure)
    worker.push_success_handler(handle_job_success)
    
    logger.info(f"Worker {worker_name} starting work loop")
    worker.work(with_scheduler=True)
except Exception as e:
    logger.critical(f"Worker {worker_name} failed to start: {e}", exc_info=True)
    raise