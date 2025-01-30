import os
import sys
import subprocess
import psutil
from pathlib import Path
from utils.database import get_redis_client
from rq import Worker
import socket

def spawn_workers(num_workers: int = None):
    """
    Spawn the specified number of RQ workers.
    
    Args:
        num_workers (int): Number of workers to spawn. If None, uses WORKER_COUNT env variable
    """
    if num_workers is None:
        num_workers = int(os.getenv('WORKER_COUNT', '4'))  # Default to 4 workers if not specified
    
    worker_script = Path(__file__).parent / 'worker.py'
    
    processes = []
    for _ in range(num_workers):
        # Start worker without capturing output, allowing it to use its own stdout/stderr
        process = subprocess.Popen(
            [sys.executable, str(worker_script)],
            # Don't capture output - let workers manage their own I/O
            stdout=None,
            stderr=None,
            # Create new process group so workers stay alive if parent dies
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        )
        processes.append(process)
    
    return processes

def check_workers(processes):
    """
    Check the status of worker processes and return their status information.
    
    Args:
        processes (list): List of subprocess.Popen objects representing workers
        
    Returns:
        list: List of dictionaries containing status info for each worker
    """
    redis_conn = get_redis_client()
    rq_workers = Worker.all(connection=redis_conn)
    
    # RQ worker names are in format: 'hostname.pid.timestamp'
    hostname = socket.gethostname()
    worker_jobs = {}
    for w in rq_workers:
        try:
            # Extract PID from worker name
            pid = int(w.name.split('.')[1])
            worker_jobs[pid] = w.get_current_job()
        except (IndexError, ValueError):
            continue
    
    status_info = []
    for i, process in enumerate(processes):
        try:
            # Use psutil to check process status without blocking
            psutil_process = psutil.Process(process.pid)
            is_running = psutil_process.is_running()
            
            current_job = worker_jobs.get(process.pid)
            
            if is_running:
                status = {
                    'worker_id': i + 1,
                    'status': 'running',
                    'pid': process.pid,
                    'cpu_percent': psutil_process.cpu_percent(),
                    'memory_percent': psutil_process.memory_percent(),
                    'current_job': {
                        'quiz_id': current_job.args[0] if current_job and current_job.args else None,
                        'job_id': current_job.id if current_job else None,
                        'status': current_job.get_status() if current_job else 'idle'
                    } if current_job else None
                }
            else:
                status = {
                    'worker_id': i + 1,
                    'status': 'terminated',
                    'pid': process.pid,
                    'return_code': process.returncode if process.returncode is not None else 0
                }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            status = {
                'worker_id': i + 1,
                'status': 'terminated',
                'pid': process.pid,
                'return_code': process.returncode if process.returncode is not None else 0
            }
        
        status_info.append(status)
    return status_info

if __name__ == '__main__':
    spawn_workers()