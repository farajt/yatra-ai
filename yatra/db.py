"""PostgreSQL connection pool + LangGraph checkpointer.

Replaces the old single global psycopg connection, which:
  * crashed the app at import time if Postgres was down
  * was shared unsafely across concurrent Streamlit sessions
"""
import logging
from functools import lru_cache

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool, PoolTimeout

from yatra.config import get_settings
from yatra.errors import ConfigError
from yatra.serde import get_serializer

log = logging.getLogger(__name__)


@lru_cache
def get_pool() -> ConnectionPool:
    url = get_settings().database_url
    if not url:
        raise ConfigError("DATABASE_URL is not set. Add it to your .env file.")
    pool = ConnectionPool(
        conninfo=url,
        min_size=1,
        max_size=10,
        # Settings LangGraph's Postgres checkpointer expects.
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=True,
    )
    try:
        pool.wait(timeout=10)
    except PoolTimeout as e:
        pool.close()
        get_pool.cache_clear()
        raise ConfigError(
            "Could not connect to PostgreSQL within 10s. Is the server running and is "
            "DATABASE_URL correct?"
        ) from e
    log.info("PostgreSQL pool ready")
    return pool


@lru_cache
def get_checkpointer() -> PostgresSaver:
    """Short-term memory: saves graph state per thread_id (needed for interrupts / HITL)."""
    checkpointer = PostgresSaver(get_pool(), serde=get_serializer())
    checkpointer.setup()  # idempotent — creates tables on first run
    return checkpointer


def check_db() -> None:
    """Raise if the database is unreachable."""
    with get_pool().connection() as conn:
        conn.execute("SELECT 1")


def close_db() -> None:
    if get_pool.cache_info().currsize:
        get_pool().close()
        get_pool.cache_clear()
        get_checkpointer.cache_clear()
