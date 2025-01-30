import os
import sys
import subprocess
import psutil
from pathlib import Path
from utils.database import get_redis_client
from rq import Worker
import socket
from utils.logger import logger
import json
from datetime import datetime

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
        
        # Clean up registry of terminated workers
        for w in rq_workers:
            try:
                pid = int(w.name.split('.')[1])
                if not psutil.pid_exists(pid):
                    w.register_death()
                    logger.info(f"Cleaned up registry for terminated worker {pid}")
            except (IndexError, ValueError):
                continue
        
        # Refresh worker list after cleanup
        rq_workers = Worker.all(connection=redis_conn)
        worker_jobs = {}
        
        for w in rq_workers:
            try:
                pid = int(w.name.split('.')[1])
                current_job = w.get_current_job()
                # Ensure job data is JSON serializable
                if current_job:
                    worker_jobs[pid] = {
                        'args': [str(arg) for arg in (current_job.args or [])],
                        'id': str(current_job.id),
                        'status': current_job.get_status()
                    }
            except (IndexError, ValueError) as e:
                logger.warning(f"Could not parse worker name: {w.name}", exc_info=True)
                continue
            except Exception as e:
                logger.error(f"Error getting job info for worker {w.name}: {str(e)}", exc_info=True)
                continue
        
        status_info = []
        for i, process in enumerate(processes):
            try:
                is_running = psutil.pid_exists(process.pid)
                if is_running:
                    try:
                        psutil_process = psutil.Process(process.pid)
                        if not psutil_process.is_running() or psutil_process.status() == 'zombie':
                            is_running = False
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        is_running = False
                
                current_job = worker_jobs.get(process.pid)
                
                if is_running:
                    try:
                        psutil_process = psutil.Process(process.pid)
                        cpu_percent = psutil_process.cpu_percent()
                        memory_percent = psutil_process.memory_percent()
                        
                        status = {
                            'worker_id': i + 1,
                            'status': 'running',
                            'pid': process.pid,
                            'cpu_percent': float(cpu_percent),
                            'memory_percent': float(memory_percent),
                            'current_job': {
                                'quiz_id': current_job['args'][0] if current_job and current_job['args'] else None,
                                'job_id': current_job['id'] if current_job else None,
                                'status': current_job['status'] if current_job else 'idle'
                            } if current_job else None
                        }
                        
                        if current_job:
                            logger.info(f"Worker {process.pid} is processing job {current_job['id']}")
                            
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        is_running = False
                    except Exception as e:
                        logger.error(f"Error getting process stats for {process.pid}: {str(e)}", exc_info=True)
                        is_running = False
                
                if not is_running:
                    logger.warning(f"Worker {process.pid} is not running")
                    status = {
                        'worker_id': i + 1,
                        'status': 'terminated',
                        'pid': process.pid,
                        'return_code': process.returncode if process.returncode is not None else 0
                    }
                    
            except Exception as e:
                logger.error(f"Error checking worker {process.pid}: {str(e)}", exc_info=True)
                status = {
                    'worker_id': i + 1,
                    'status': 'terminated',
                    'pid': process.pid,
                    'return_code': process.returncode if process.returncode is not None else 0
                }
            
            status_info.append(status)
        
        # Validate JSON serialization before returning
        try:
            json.dumps(status_info)
        except (TypeError, ValueError) as e:
            logger.error(f"Status info is not JSON serializable: {str(e)}", exc_info=True)
            # Return a safe version with only essential info
            status_info = [{
                'worker_id': s['worker_id'],
                'status': s['status'],
                'pid': s['pid']
            } for s in status_info]
        
        active_workers = sum(1 for s in status_info if s['status'] == 'running')
        logger.info(f"Status check complete. {active_workers}/{len(processes)} workers active")
        return status_info
        
    except Exception as e:
        logger.critical("Critical error during worker status check", exc_info=True)
        # Return minimal safe status on error
        return [{
            'worker_id': i + 1,
            'status': 'unknown',
            'pid': p.pid
        } for i, p in enumerate(processes)]

if __name__ == '__main__':
    spawn_workers()