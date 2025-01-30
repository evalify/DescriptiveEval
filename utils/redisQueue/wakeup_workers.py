import os
import sys
import subprocess
import psutil
from pathlib import Path
from utils.database import get_redis_client
from rq import Worker
import socket
from utils.logger import logger

def spawn_workers(num_workers: int = None):
    """
    Spawn the specified number of RQ workers.
    
    Args:
        num_workers (int): Number of workers to spawn. If None, uses WORKER_COUNT env variable
    """
    if num_workers is None:
        num_workers = int(os.getenv('WORKER_COUNT', '4'))
    
    worker_script = Path(__file__).parent / 'worker.py'
    logger.info(f"Spawning {num_workers} workers using script: {worker_script}")
    
    processes = []
    for i in range(num_workers):
        try:
            process = subprocess.Popen(
                [sys.executable, str(worker_script)],
                stdout=None,
                stderr=None,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )
            logger.info(f"Worker {i+1}/{num_workers} spawned with PID: {process.pid}")
            processes.append(process)
        except Exception as e:
            logger.error(f"Failed to spawn worker {i+1}/{num_workers}", exc_info=True)
            for process in processes:
                try:
                    process.terminate()
                    process.wait()
                    logger.info(f"Cleaned up worker with PID: {process.pid}")
                except Exception as cleanup_error:
                    logger.error(f"Failed to clean up worker with PID: {process.pid}", exc_info=True)
            raise e
    
    logger.info(f"Successfully spawned {len(processes)} workers")
    return processes

def check_workers(processes):
    """
    Check the status of worker processes and return their status information.
    
    Args:
        processes (list): List of subprocess.Popen objects representing workers
        
    Returns:
        list: List of dictionaries containing status info for each worker
    """
    logger.debug("Starting worker status check")
    try:
        redis_conn = get_redis_client()
        rq_workers = Worker.all(connection=redis_conn)
        logger.debug(f"Found {len(rq_workers)} registered RQ workers")
        
        hostname = socket.gethostname()
        worker_jobs = {}
        for w in rq_workers:
            try:
                pid = int(w.name.split('.')[1])
                worker_jobs[pid] = w.get_current_job()
            except (IndexError, ValueError) as e:
                logger.warning(f"Could not parse worker name: {w.name}", exc_info=True)
                continue
        
        status_info = []
        for i, process in enumerate(processes):
            try:
                psutil_process = psutil.Process(process.pid)
                is_running = psutil_process.is_running()
                current_job = worker_jobs.get(process.pid)
                
                if is_running:
                    cpu_percent = psutil_process.cpu_percent()
                    memory_percent = psutil_process.memory_percent()
                    logger.debug(f"Worker {process.pid} stats - CPU: {cpu_percent}%, Memory: {memory_percent}%")
                    
                    status = {
                        'worker_id': i + 1,
                        'status': 'running',
                        'pid': process.pid,
                        'cpu_percent': cpu_percent,
                        'memory_percent': memory_percent,
                        'current_job': {
                            'quiz_id': current_job.args[0] if current_job and current_job.args else None,
                            'job_id': current_job.id if current_job else None,
                            'status': current_job.get_status() if current_job else 'idle'
                        } if current_job else None
                    }
                    
                    if current_job:
                        logger.info(f"Worker {process.pid} is processing job {current_job.id}")
                    
                else:
                    logger.warning(f"Worker {process.pid} is not running")
                    status = {
                        'worker_id': i + 1,
                        'status': 'terminated',
                        'pid': process.pid,
                        'return_code': process.returncode if process.returncode is not None else 0
                    }
                    
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                logger.error(f"Error checking worker {process.pid}: {str(e)}", exc_info=True)
                status = {
                    'worker_id': i + 1,
                    'status': 'terminated',
                    'pid': process.pid,
                    'return_code': process.returncode if process.returncode is not None else 0
                }
            
            status_info.append(status)
        
        active_workers = sum(1 for s in status_info if s['status'] == 'running')
        logger.info(f"Status check complete. {active_workers}/{len(processes)} workers active")
        return status_info
        
    except Exception as e:
        logger.critical("Critical error during worker status check", exc_info=True)
        raise

if __name__ == '__main__':
    spawn_workers()