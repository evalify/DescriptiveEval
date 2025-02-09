import pytest
from fastapi.testclient import TestClient
import psutil
import time
from rq import Queue, Worker
from app import app
from utils.database import get_redis_client

@pytest.fixture
def test_client():
    with TestClient(app) as client:
        yield client

def test_worker_lifecycle_startup(test_client):
    """Test that workers are properly spawned during application startup"""
    # Check if workers are initialized in app state
    assert hasattr(app.state, 'worker_processes')
    assert len(app.state.worker_processes) > 0
    
    # Verify workers are running
    running_workers = [p for p in app.state.worker_processes if psutil.pid_exists(p.pid)]
    assert len(running_workers) == len(app.state.worker_processes)
    
    # Check Redis registration
    redis_conn = get_redis_client()
    rq_workers = Worker.all(connection=redis_conn)
    assert len(rq_workers) >= len(app.state.worker_processes)

def test_worker_status_endpoint(test_client):
    """Test the worker status endpoint"""
    response = test_client.get("/workers/status")
    assert response.status_code == 200
    
    data = response.json()
    assert 'workers' in data
    assert 'active_workers' in data
    assert 'total_workers' in data
    assert 'queue_info' in data
    assert 'jobs_summary' in data
    
    # Verify worker information
    for worker in data['workers']:
        assert 'worker_id' in worker
        assert 'status' in worker
        assert 'pid' in worker
        if worker['status'] == 'running':
            assert 'current' in worker
            assert 'cpu_percent' in worker['current']
            assert 'memory_percent' in worker['current']

def test_kill_and_replace_worker(test_client):
    """Test killing a worker and optionally replacing it"""
    # Get initial worker status
    initial_status = test_client.get("/workers/status").json()
    initial_worker = next((w for w in initial_status['workers'] if w['status'] == 'running'), None)
    assert initial_worker is not None
    
    # Kill worker without replacement
    response = test_client.post(f"/workers/kill/{initial_worker['pid']}?spawn_replacement=false")
    assert response.status_code == 200
    time.sleep(1)  # Give time for worker to terminate
    
    # Verify worker was killed
    after_kill = test_client.get("/workers/status").json()
    assert len([w for w in after_kill['workers'] if w['status'] == 'running']) < len(initial_status['workers'])
    
    # Kill worker with replacement
    running_worker = next((w for w in after_kill['workers'] if w['status'] == 'running'), None)
    assert running_worker is not None
    
    response = test_client.post(f"/workers/kill/{running_worker['pid']}?spawn_replacement=true")
    assert response.status_code == 200
    assert 'replacement_worker' in response.json()
    time.sleep(1)  # Give time for new worker to start
    
    # Verify worker count is maintained
    final_status = test_client.get("/workers/status").json()
    print(final_status)
    assert len([w for w in final_status['workers'] if w['status'] == 'running']) == len(after_kill['workers']), \
    f"Worker count not maintained after replacement ({len(final_status['workers'])} workers running)" + \
    f"Expected {len(initial_status['workers'])} workers"

def test_worker_job_assignment(test_client):
    """Test that jobs are properly assigned to workers"""
    # Create a test job
    redis_conn = get_redis_client()
    queue = Queue('task_queue', connection=redis_conn)
    
    # Add a test job
    job = queue.enqueue(lambda x: x + 1, args=(1,), job_timeout=10)
    time.sleep(1)  # Give time for job assignment
    
    # Check worker status
    response = test_client.get("/workers/status")
    assert response.status_code == 200
    data = response.json()
    
    # Verify job appears in queue info
    assert 'queue_info' in data
    jobs_info = data['queue_info']
    assert any(j['job_id'] == job.id for j in jobs_info['queued'] + jobs_info.get('completed', []))
    
    # Verify job is assigned to a worker
    workers_with_jobs = [w for w in data['workers'] if w.get('current_job')]
    if job.is_finished:
        assert any(w['current_job']['job_id'] == job.id for w in workers_with_jobs)

@pytest.mark.asyncio
async def test_application_shutdown():
    """Test proper cleanup of workers during application shutdown"""
    # Store initial worker PIDs
    initial_pids = [p.pid for p in app.state.worker_processes]
    
    # Simulate application shutdown by calling lifespan cleanup
    async with app.router.lifespan_context(app):
        pass  # Context manager will handle startup/shutdown
    
    # Verify all workers are terminated
    for pid in initial_pids:
        assert not psutil.pid_exists(pid), f"Worker {pid} still running after shutdown"
    
    # Verify Redis cleanup
    redis_conn = get_redis_client()
    remaining_workers = Worker.all(connection=redis_conn)
    assert not any(str(pid) in w.name for w in remaining_workers for pid in initial_pids)