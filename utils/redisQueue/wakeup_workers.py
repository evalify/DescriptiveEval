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
import time
from datetime import datetime
import asyncio

_worker_stats = {}

def _update_worker_stats(pid, cpu_percent, memory_percent, current_job):
    """Track worker performance over time"""
    now = datetime.now()
    if pid not in _worker_stats:
        _worker_stats[pid] = {
            'cpu_history': [],
            'memory_history': [],
            'jobs_completed': 0,
            'last_job_completed': None,
            'uptime_start': now
        }
    
    stats = _worker_stats[pid]
    # Keep last 60 measurements (10 minutes at 10-second intervals)
    stats['cpu_history'].append((now, cpu_percent))
    stats['memory_history'].append((now, memory_percent))
    if len(stats['cpu_history']) > 60:
        stats['cpu_history'].pop(0)
        stats['memory_history'].pop(0)
    
    # Update job completion stats
    if current_job and current_job.get('status') == 'finished':
        if stats['last_job_completed'] != current_job.get('job_id'):
            stats['jobs_completed'] += 1
            stats['last_job_completed'] = current_job.get('job_id')

async def verify_worker_registration(redis_conn, worker_processes, timeout=30):
    """
    Verify that workers are properly registered in Redis
    
    Args:
        redis_conn: Redis connection
        worker_processes: List of worker processes
        timeout: Maximum time to wait for registration in seconds
        
    Returns:
        bool: True if all workers registered successfully
    """
    end_time = time.time() + timeout
    while time.time() < end_time:
        registered_workers = Worker.all(connection=redis_conn)
        registered_pids = {
            int(w.name.split('.')[1]) 
            for w in registered_workers 
            if len(w.name.split('.')) > 1 and w.name.split('.')[1].isdigit()
        }
        spawned_pids = {p.pid for p in worker_processes}
        
        if registered_pids >= spawned_pids:
            logger.info(f"All workers registered successfully: {len(registered_pids)} workers")
            return True
            
        remaining_time = end_time - time.time()
        if remaining_time <= 0:
            break
        await asyncio.sleep(min(1, remaining_time))
    
    missing_pids = spawned_pids - registered_pids
    logger.error(f"Worker registration timeout. Missing PIDs: {missing_pids}")
    return False

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
            env = os.environ.copy()
            env['PYTHONPATH'] = str(Path(__file__).parent.parent.parent)
            
            process = subprocess.Popen(
                [sys.executable, str(worker_script)],
                stdout=subprocess.PIPE if os.name == 'nt' else None,
                stderr=subprocess.PIPE if os.name == 'nt' else None,
                env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )
            logger.info(f"Worker {i+1}/{num_workers} spawned with PID: {process.pid}")
            # wait for worker to start
            time.sleep(1)
            processes.append(process)

            # Quick check if process is still running
            if not psutil.pid_exists(process.pid):
                raise RuntimeError(f"Worker process {process.pid} died immediately after spawning")
            
        except subprocess.SubprocessError as e:
            logger.error(f"Failed to spawn worker {i+1}/{num_workers} due to subprocess error", exc_info=True)
            # Clean up any workers that were successfully spawned
            for p in processes:
                try:
                    if psutil.pid_exists(p.pid):
                        psutil.Process(p.pid).terminate()
                        psutil.Process(p.pid).wait(timeout=5)
                except Exception as cleanup_error:
                    logger.error(f"Failed to clean up worker with PID: {p.pid}", exc_info=True)
            raise e
            # Quick check if process is still running
                
        except Exception as e:
            logger.error(f"Failed to spawn worker {i+1}/{num_workers}", exc_info=True)
            # Clean up any workers that were successfully spawned
            for p in processes:
                try:
                    if psutil.pid_exists(p.pid):
                        psutil.Process(p.pid).terminate()
                        psutil.Process(p.pid).wait(timeout=5)
                except Exception as cleanup_error:
                    logger.error(f"Failed to clean up worker with PID: {p.pid}", exc_info=True)
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
        
        # Clean up registry and stats of terminated workers
        for w in rq_workers:
            try:
                pid = int(w.name.split('.')[1])
                if not psutil.pid_exists(pid):
                    w.teardown()
                    if pid in _worker_stats:
                        del _worker_stats[pid]
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
                if current_job:
                    worker_jobs[pid] = {
                        'args': [str(arg) for arg in (current_job.args or [])],
                        'id': str(current_job.id),
                        'status': current_job.get_status(),
                        'started_at': current_job.started_at.isoformat() if current_job.started_at else None,
                        'enqueued_at': current_job.enqueued_at.isoformat() if current_job.enqueued_at else None
                    }
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
                        
                        # Update worker stats
                        _update_worker_stats(process.pid, cpu_percent, memory_percent, current_job)
                        worker_stats = _worker_stats.get(process.pid, {})
                        
                        # Calculate averages from history
                        cpu_history = worker_stats.get('cpu_history', [])
                        memory_history = worker_stats.get('memory_history', [])
                        avg_cpu = sum(c for _, c in cpu_history) / len(cpu_history) if cpu_history else 0
                        avg_memory = sum(m for _, m in memory_history) / len(memory_history) if memory_history else 0
                        
                        status = {
                            'worker_id': i + 1,
                            'status': 'running',
                            'pid': process.pid,
                            'current': {
                                'cpu_percent': float(cpu_percent),
                                'memory_percent': float(memory_percent)
                            },
                            'averages': {
                                'cpu_percent': float(avg_cpu),
                                'memory_percent': float(avg_memory)
                            },
                            'stats': {
                                'uptime_seconds': (datetime.now() - worker_stats.get('uptime_start', datetime.now())).total_seconds(),
                                'jobs_completed': worker_stats.get('jobs_completed', 0)
                            },
                            'current_job': {
                                'quiz_id': current_job['args'][0] if current_job and current_job['args'] else None,
                                'job_id': current_job['id'] if current_job else None,
                                'status': current_job['status'] if current_job else 'idle',
                                'started_at': current_job['started_at'] if current_job else None,
                                'enqueued_at': current_job['enqueued_at'] if current_job else None,
                                'duration': 0
                                if not current_job or not current_job['started_at']
                                else (
                                    lambda: (
                                        datetime.now() - datetime.fromisoformat(current_job['started_at'])
                                    ).total_seconds()
                                    if current_job and current_job['started_at']
                                    else 0
                                )()
                            } if current_job else None
                        }
                        
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        is_running = False
                    except Exception as e:
                        logger.error(f"Error getting process stats for {process.pid}: {str(e)}", exc_info=True)
                        is_running = False
                
                if not is_running:
                    if process.pid in _worker_stats:
                        del _worker_stats[process.pid]
                    status = {
                        'worker_id': i + 1,
                        'status': 'terminated',
                        'pid': process.pid,
                        'return_code': process.returncode if process.returncode is not None else 0
                    }
                    
            except Exception as e:
                logger.error(f"Error checking worker {process.pid}: {str(e)}", exc_info=True)
                if process.pid in _worker_stats:
                    del _worker_stats[process.pid]
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