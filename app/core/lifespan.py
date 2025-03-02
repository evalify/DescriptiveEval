import asyncio
import os
import time
from contextlib import asynccontextmanager
import psutil
from rq import Worker, Queue
from rq.command import send_stop_job_command
from fastapi import FastAPI
from app.database.redis import get_redis_client
from app.utils.wakeup_workers import spawn_workers
from app.core.logger import logger
from rq.job import JobStatus


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_conn = get_redis_client()

    # Display ASCII banner
    try:
        import pyfiglet
        import termcolor
    except ImportError:
        print("DescEval")
    except Exception as e:
        logger.error(f"Error displaying ASCII banner: {str(e)}")
    else:
        ascii_banner = pyfiglet.figlet_format("Desc Eval", font="slant")
        colored_ascii_banner = termcolor.colored(ascii_banner, color="cyan")
        print(colored_ascii_banner)
    
    print("Initializing Evaluation Backend for Evalify...")

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

    except Exception:
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
                                # TODO: Add this to config.ini for easy toggling
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
