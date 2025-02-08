from redis import Redis
import time
from utils.logger import logger

class QuizLock:
    """Redis-based distributed lock for quiz evaluation"""
    
    def __init__(self, redis_client: Redis, quiz_id: str, timeout: int = 3600):
        """
        Initialize a quiz lock
        
        Args:
            redis_client: Redis client instance
            quiz_id: Quiz ID to lock
            timeout: Lock timeout in seconds (default: 1 hour)
        """
        self.redis = redis_client
        self.quiz_id = quiz_id
        self.timeout = timeout
        self.lock_key = f"quiz_lock:{quiz_id}"
        
    def acquire(self, blocking: bool = True, retry_interval: float = 1.0) -> bool:
        """
        Acquire the lock
        
        Args:
            blocking: If True, wait until lock is acquired
            retry_interval: Time between retries in seconds
            
        Returns:
            bool: True if lock was acquired, False otherwise
        """
        while True:
            # Try to set the lock with NX (only if not exists)
            acquired = self.redis.set(
                self.lock_key,
                "locked",
                nx=True,
                ex=self.timeout
            )
            
            if acquired:
                logger.debug(f"Lock acquired for quiz {self.quiz_id}")
                return True
                
            if not blocking:
                logger.debug(f"Failed to acquire lock for quiz {self.quiz_id} (non-blocking)")
                return False
                
            logger.debug(f"Waiting to acquire lock for quiz {self.quiz_id}")
            time.sleep(retry_interval)
    
    def release(self) -> bool:
        """
        Release the lock
        
        Returns:
            bool: True if lock was released, False if it didn't exist
        """
        released = self.redis.delete(self.lock_key)
        if released:
            logger.debug(f"Lock released for quiz {self.quiz_id}")
        return bool(released)
    
    def is_locked(self) -> bool:
        """
        Check if quiz is currently locked
        
        Returns:
            bool: True if locked, False otherwise
        """
        return bool(self.redis.exists(self.lock_key))

    def get_lock_ttl(self) -> int:
        """
        Get remaining lock time
        
        Returns:
            int: Remaining time in seconds, -1 if not locked
        """
        return self.redis.ttl(self.lock_key)

    def __enter__(self):
        """Context manager entry"""
        self.acquire()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.release()