import os
import sys

# Add project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(project_root)

from rq import Worker
from utils.database import get_redis_client

if __name__ == '__main__':
    worker = Worker(['task_queue'], connection=get_redis_client())
    worker.work()