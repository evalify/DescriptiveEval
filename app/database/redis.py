from redis import Redis, ConnectionPool, StrictRedis

from app.config.constants import REDIS_HOST, REDIS_PORT, REDIS_DB


redis_pool = ConnectionPool(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    decode_responses=True,
    max_connections=20,
)


def get_redis_client() -> Redis:
    """Direct Redis connection for workers"""
    return StrictRedis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=False,
    )


def get_redis_pool() -> Redis:
    """Pooled Redis connection for API endpoints"""
    return Redis(connection_pool=redis_pool)
