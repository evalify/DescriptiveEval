import redis
from redis import Redis
import os
from redis import ConnectionPool

redis_pool = ConnectionPool(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=0,
    decode_responses=True,
    max_connections=20,
)


def get_redis_client() -> Redis:
    """Direct Redis connection for workers"""
    return redis.StrictRedis(
        host=os.getenv("REDIS_HOST", "172.17.9.74"),
        port=int(os.getenv("REDIS_PORT", 32768)),
        db=int(os.getenv("REDIS_DB", 2)),
        decode_responses=False,
    )


def get_redis_pool() -> Redis:
    """Pooled Redis connection for API endpoints"""
    return Redis(connection_pool=redis_pool)
