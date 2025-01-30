import os
import sys
import socket
import time

# Add project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(project_root)

from rq import Worker
from utils.database import get_redis_client

# Create a unique worker name using hostname.pid.timestamp format
hostname = socket.gethostname()
pid = os.getpid()
timestamp = int(time.time())
worker_name = f"{hostname}.{pid}.{timestamp}"

redis_conn = get_redis_client()
worker = Worker(['task_queue'], connection=redis_conn, name=worker_name)
worker.work(with_scheduler=True)