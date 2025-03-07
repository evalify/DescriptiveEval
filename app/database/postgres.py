"""Database utilities for handling connections"""

from contextlib import contextmanager
import time
import random
from typing import Tuple, Optional, Dict

import psycopg2
from psycopg2.extensions import (
    connection as postgres_connection,
    ISOLATION_LEVEL_READ_COMMITTED,
)
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.errors import ActiveSqlTransaction, QueryCanceledError
import uuid

from app.core.logger import logger
from app.config.constants import COCKROACH_DB
from .database_monitoring import QueryMonitor

# Clean up pools on module unload
import atexit


keepalive_kwargs = {
    "keepalives": 1,
    "keepalives_idle": 60,  # Send keepalive after 60s of inactivity
    "keepalives_interval": 10,  # Resend unacknowledged keepalives every 10s
    "keepalives_count": 5,  # Mark connection dead after 5 failed keepalives
}

# Initialize connection pools
postgres_pool = ThreadedConnectionPool(
    5,
    20,
    COCKROACH_DB,
    options="-c statement_timeout=30000",  # 30 second timeout
    **keepalive_kwargs,
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
    conn = psycopg2.connect(  # FIXME: Temporary override of pool
        COCKROACH_DB,
        options="-c statement_timeout=30000",  # 30 second timeout
    )
    try:
        yield conn
    finally:
        conn.close()


def get_db_connection_no_context():
    """Get a connection without context manager"""
    conn = psycopg2.connect(
        COCKROACH_DB,
        options="-c statement_timeout=30000",  # 30 second timeout
    )
    conn.autocommit = True  # Set autocommit mode
    # Get cursor
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    return conn, cursor


@contextmanager
def get_db_cursor():
    """Get a connection and cursor from the pool and return them when done"""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cursor, conn
        finally:
            cursor.close()


def get_postgres_cursor() -> Tuple[RealDictCursor, postgres_connection]:
    """Direct database connection for workers with proper timeouts"""
    my_connection = psycopg2.connect(
        COCKROACH_DB,
        options="-c statement_timeout=30000",  # 30 second timeout
    )
    my_connection.set_session(isolation_level=ISOLATION_LEVEL_READ_COMMITTED)
    cursor = my_connection.cursor(cursor_factory=RealDictCursor)
    return cursor, my_connection


def cancel_long_running_queries(conn, pid: int, age_threshold: int = 30):
    """Cancel queries running longer than the threshold"""
    try:
        with conn.cursor() as cancel_cursor:
            cancel_cursor.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE pid = %s
                AND state = 'active'
                AND state_change < NOW() - INTERVAL '%s seconds'
                AND query NOT LIKE '%%pg_terminate_backend%%'
            """,
                (pid, age_threshold),
            )

            # Log if any query was terminated
            if cancel_cursor.rowcount > 0:
                logger.warning(
                    f"Forcibly terminated query on connection {pid} after {age_threshold}s"
                )
                return True
    except Exception as e:
        logger.error(f"Failed to cancel long-running query: {str(e)}")
    return False


def execute_with_timeout(
    cursor, query: str, params=None, timeout: int = 30, context: Optional[Dict] = None
):
    """Execute a query with timeout, monitoring and force cancellation if needed"""
    query_id = str(uuid.uuid4())
    monitor = QueryMonitor.get_instance()

    try:
        # Start monitoring this query
        monitor.start_query(query_id, query, params, context)

        # Set statement-level timeout
        cursor.execute(f"SET LOCAL statement_timeout = {timeout * 1000}")

        start_time = time.time()
        cursor.execute(query, params)
        duration = time.time() - start_time

        if duration > timeout * 0.8:  # Log slow queries
            logger.warning(f"Slow query took {duration:.2f}s: {query[:100]}...")

        monitor.end_query(query_id, status="completed")
        return cursor

    except QueryCanceledError as e:
        monitor.end_query(query_id, status="timeout", error=str(e))
        logger.error(f"Query timed out after {timeout}s: {query[:100]}...")

        # Force cancel if query is still running
        if hasattr(cursor.connection, "get_backend_pid"):
            backend_pid = cursor.connection.get_backend_pid()
            cancel_long_running_queries(cursor.connection, backend_pid, timeout)
        raise

    except Exception as e:
        monitor.end_query(query_id, status="error", error=str(e))
        logger.error(f"Query failed: {str(e)}")
        raise

    finally:
        # Check for any other stuck queries
        stuck_queries = monitor.check_stuck_queries(timeout)
        if stuck_queries:
            logger.error(f"Found {len(stuck_queries)} stuck queries during execution")
            for stuck_id, info in stuck_queries.items():
                if hasattr(cursor.connection, "get_backend_pid"):
                    backend_pid = cursor.connection.get_backend_pid()
                    cancel_long_running_queries(cursor.connection, backend_pid, timeout)


@contextmanager
def safe_transaction(cursor, conn, timeout: int = 30):
    """Handle transaction states safely with timeouts and forced cancellation"""
    max_attempts = 5
    attempt = 0

    while attempt < max_attempts:
        try:
            # Ensure clean state
            if conn.status != psycopg2.extensions.STATUS_READY:
                try:
                    conn.rollback()
                except psycopg2.Error:
                    pass

            # Set session-level timeout
            execute_with_timeout(
                cursor, f"SET LOCAL statement_timeout = {timeout * 1000}"
            )

            # Store the start time and backend PID
            start_time = time.time()
            backend_pid = (
                conn.get_backend_pid() if hasattr(conn, "get_backend_pid") else None
            )

            yield

            duration = time.time() - start_time
            if duration >= timeout:
                # Force cancel if we somehow exceeded timeout
                if backend_pid:
                    cancel_long_running_queries(conn, backend_pid, timeout)
                raise QueryCanceledError(f"Transaction exceeded timeout of {timeout}s")

            conn.commit()
            break

        except (psycopg2.Error, ActiveSqlTransaction) as e:
            logger.warning(f"Transaction attempt {attempt + 1} failed: {str(e)}")
            try:
                conn.rollback()
            except Exception:
                pass

            attempt += 1
            if attempt == max_attempts:
                raise

            # Get fresh cursor if needed
            if cursor.closed:
                cursor = conn.cursor(cursor_factory=RealDictCursor)

            time.sleep(2**attempt)  # Exponential backoff

        except Exception as e:
            logger.error(f"Unexpected error in transaction: {str(e)}")
            try:
                conn.rollback()
            except psycopg2.Error:
                pass  # Ignore rollback errors
            raise


@atexit.register
def cleanup_pools():
    """Clean up connection pools on exit"""
    postgres_pool.closeall()


if __name__ == "__main__":
    import asyncio

    async def query(cursor, conn, response_id):
        cursor.execute(
            """
                        UPDATE "QuizResult" 
                        SET score = 3, 
                        "isEvaluated" = 'UNEVALUATED'
                        WHERE id = %s
                       """,
            (response_id,),
        )

        cursor.execute('SELECT * FROM "QuizResult" WHERE id = %s', (response_id,))
        print(cursor.fetchall())
        print(f"{response_id=!r}")
        conn.commit()

    async def main():
        with get_db_cursor() as (cursor, conn):
            await query(
                cursor=cursor, conn=conn, response_id="cm4wmiy5y0003i71jf0sybng2"
            )

    asyncio.run(main())
