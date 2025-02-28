import os
import signal
import socket
import sys
import time
import psutil
from rq import Worker

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))) # Add project root to Python path
from app.core.logger import logger, QuizLogger
from app.database.redis import get_redis_client

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

class EnhancedWorker(Worker):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.custom_job_start_time = None   # Add custom to prevent interference with base class
        self.custom_total_jobs_processed = 0
        self.custom_total_jobs_failed = 0
        self.custom_last_heartbeat = time.time()
        self.custom_health_check_interval = 30  # seconds

    def heartbeat(self, *args, **kwargs):
        """Enhanced heartbeat with health check"""
        current_time = time.time()
        if current_time - self.custom_last_heartbeat > self.custom_health_check_interval:
            # Log health status
            memory_usage = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024  # MB
            logger.debug(
                f"Worker {worker_name} health check: "
                f"Jobs processed: {self.custom_total_jobs_processed}, "
                f"Failed: {self.custom_total_jobs_failed}, "
                f"Memory usage: {memory_usage:.2f}MB"
            )
        super().heartbeat(*args, **kwargs)
        self.custom_last_heartbeat = current_time

try:
    redis_conn = get_redis_client()
    logger.info(f"Worker {worker_name} initializing with Redis connection")
    
    worker = EnhancedWorker(['task_queue'], connection=redis_conn, name=worker_name, worker_ttl=int(os.getenv('WORKER_TTL', 3600)))
    logger.info(f"Worker {worker_name} successfully created")
    
    # Create task queue for callbacks
    # task_queue = Queue('task_queue', connection=redis_conn)
    
    def handle_job_failure(job, *args, **kwargs):
        """Handle job failures"""
        if isinstance(kwargs.get('exc_type'), (SystemExit, KeyboardInterrupt)):
            logger.warning(f"Worker {worker_name}: Job {job.id} cancelled by user")
            return False  # Don't retry the job
            
        quiz_id = job.args[0] if job.args else "unknown"
        qlogger = QuizLogger(quiz_id)
        error_type = kwargs.get('exc_type').__name__ if kwargs.get('exc_type') else 'Unknown'
        error_value = str(kwargs.get('exc_value')) if kwargs.get('exc_value') else 'No details'
        
        # Enhanced error logging
        error_context = {
            'job_id': job.id,
            'quiz_id': quiz_id,
            'error_type': error_type,
            'error_value': error_value,
            'job_duration': time.time() - worker.custom_job_start_time if worker.custom_job_start_time else None,
            'memory_usage': psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024  # MB
        }
        
        qlogger.error(f"Job {job.id} failed", extra=error_context)
        logger.error(f"Worker {worker_name}: Job {job.id} failed", extra=error_context)
        return True  # Retry other types of failures

    def handle_job_success(job, queue, started_job_registry):
        """Handle successful job completion"""
        quiz_id = job.args[0] if job.args else "unknown"
        qlogger = QuizLogger(quiz_id)
        
        # Enhanced success logging
        worker.custom_total_jobs_processed += 1
        success_context = {
            'job_id': job.id,
            'quiz_id': quiz_id,
            'job_duration': time.time() - worker.custom_job_start_time if worker.custom_job_start_time else None,
            'memory_usage': psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024,  # MB
            'total_jobs_processed': worker.custom_total_jobs_processed
        }
        
        qlogger.info(f"Job {job.id} completed successfully", extra=success_context)
        logger.info(f"Worker {worker_name}: Job {job.id} completed", extra=success_context)

    # Register handlers
    worker.push_exc_handler(handle_job_failure)
    worker.success_handler = handle_job_success
    
    logger.info(f"Worker {worker_name} starting work loop")
    worker.work(with_scheduler=True)

except Exception as e:
    logger.critical(f"Worker {worker_name} failed to start: {e}", exc_info=True)
    raise