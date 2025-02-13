"""Database utilities for handling connections"""

import os
from contextlib import contextmanager
import time
import random
from typing import Tuple
import redis
import psycopg2
from dotenv import load_dotenv
from psycopg2.extensions import connection as postgres_connection
from psycopg2.extras import RealDictCursor
from pymongo import MongoClient
from pymongo.database import Database
from redis import ConnectionPool, Redis
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.errors import ActiveSqlTransaction

# Clean up pools on module unload
import atexit

load_dotenv()

# Initialize connection pools
postgres_pool = ThreadedConnectionPool(
    5,
    20,
    os.getenv("COCKROACH_DB"),
)

redis_pool = ConnectionPool(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=0,
    decode_responses=True,
    max_connections=20,
)


def exponential_backoff(attempt, max_attempts=5, base_delay=0.1):
    """Implement exponential backoff with jitter"""
    if attempt >= max_attempts:
        return False
    delay = min(300, base_delay * (2**attempt))  # Cap at 5 minutes
    jitter = delay * 0.1 * random.random()
    time.sleep(delay + jitter)
    return True


@contextmanager
def get_db_connection():
    """Get a connection from the pool and return it when done"""
    conn = postgres_pool.getconn()
    try:
        yield conn
    finally:
        postgres_pool.putconn(conn)


@contextmanager
def get_db_cursor():
    """Get a connection and cursor from the pool and return them when done"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            yield cursor, conn
        finally:
            cursor.close()


def get_postgres_cursor() -> Tuple[RealDictCursor, postgres_connection]:
    """Direct database connection for workers"""
    my_connection = psycopg2.connect(os.getenv("COCKROACH_DB"))
    return my_connection.cursor(cursor_factory=RealDictCursor), my_connection


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


def get_mongo_client() -> Database:
    """MongoDB connection"""
    client = MongoClient(os.getenv("MONGODB_URI"))
    return client["Evalify"]


@contextmanager
def safe_transaction(cursor, conn):
    """Handle transaction states safely with retries"""
    max_attempts = 5
    attempt = 0

    while True:
        try:
            # Try to rollback any existing transaction
            try:
                conn.rollback()
            except psycopg2.Error:
                pass  # Ignore rollback errors

            yield
            conn.commit()
            break

        except ActiveSqlTransaction:
            # Handle active transaction error
            if not exponential_backoff(attempt, max_attempts):
                raise
            attempt += 1
            continue

        except Exception as e:
            try:
                conn.rollback()
            except psycopg2.Error:
                pass  # Ignore rollback errors
            raise


@atexit.register
def cleanup_pools():
    """Clean up connection pools on exit"""
    postgres_pool.closeall()
    redis_pool.disconnect()
