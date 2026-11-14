"""Storage for graph checkpoints (pause/resume) and the long-term store (memory, usage counter).

Default: one local SQLite file (.data/yatra.db). Nothing to install or sign up for.
Optional: PostgreSQL, used automatically when DATABASE_URL is set.

On Streamlit Community Cloud the SQLite file lives on the app's temporary disk, so saved
preferences and the daily counter reset when the app restarts. That is fine for a demo; set
DATABASE_URL to a Postgres database if you need them to survive restarts.
"""
import logging
import sqlite3
from functools import lru_cache

from yatra.config import get_settings
from yatra.errors import ConfigError
from yatra.serde import get_serializer

log = logging.getLogger(__name__)


def using_postgres() -> bool:
    return bool(get_settings().database_url.strip())


# ── SQLite (default) ──────────────────────────────────────────────────────────
def _sqlite_connect(autocommit: bool = False) -> sqlite3.Connection:
    path = get_settings().sqlite_path
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: Streamlit and FastAPI call from worker threads; LangGraph's
    # SQLite classes serialise access with their own locks. The store issues its own BEGIN,
    # so its connection must be in autocommit mode (isolation_level=None).
    conn = sqlite3.connect(str(path), check_same_thread=False,
                           **({"isolation_level": None} if autocommit else {}))
    conn.execute("PRAGMA journal_mode=WAL")   # readers don't block the writer
    return conn


@lru_cache
def _sqlite_checkpoint_conn() -> sqlite3.Connection:
    return _sqlite_connect()


@lru_cache
def _sqlite_store_conn() -> sqlite3.Connection:
    return _sqlite_connect(autocommit=True)


# ── PostgreSQL (optional) ─────────────────────────────────────────────────────
@lru_cache
def get_pool():
    from psycopg_pool import ConnectionPool, PoolTimeout

    pool = ConnectionPool(
        conninfo=get_settings().database_url,
        min_size=1,
        max_size=10,
        # Settings LangGraph's Postgres classes expect.
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=True,
    )
    try:
        pool.wait(timeout=10)
    except PoolTimeout as e:
        pool.close()
        get_pool.cache_clear()
        raise ConfigError(
            "Could not connect to PostgreSQL within 10s. Check DATABASE_URL, or leave it empty "
            "to use the built-in SQLite file."
        ) from e
    log.info("PostgreSQL pool ready")
    return pool


# ── Public API ────────────────────────────────────────────────────────────────
@lru_cache
def get_checkpointer():
    """Short-term memory: one planning session's state per thread_id (needed to pause and resume)."""
    if using_postgres():
        from langgraph.checkpoint.postgres import PostgresSaver
        saver = PostgresSaver(get_pool(), serde=get_serializer())
    else:
        from langgraph.checkpoint.sqlite import SqliteSaver
        saver = SqliteSaver(_sqlite_checkpoint_conn(), serde=get_serializer())
    saver.setup()  # creates tables on first run; safe to repeat
    return saver


@lru_cache
def get_store():
    """Long-term memory: user preferences and the public-demo usage counter."""
    if using_postgres():
        from langgraph.store.postgres import PostgresStore
        store = PostgresStore(get_pool())
    else:
        from langgraph.store.sqlite import SqliteStore
        store = SqliteStore(_sqlite_store_conn())
    store.setup()
    return store


def describe_backend() -> str:
    return "PostgreSQL" if using_postgres() else f"SQLite ({get_settings().sqlite_path.name})"


def check_db() -> None:
    """Raise if the storage cannot be used."""
    if using_postgres():
        with get_pool().connection() as conn:
            conn.execute("SELECT 1")
    else:
        _sqlite_checkpoint_conn().execute("SELECT 1")


def close_db() -> None:
    if using_postgres() and get_pool.cache_info().currsize:
        get_pool().close()
    for cached in (_sqlite_checkpoint_conn, _sqlite_store_conn):
        if cached.cache_info().currsize:
            cached().close()
        cached.cache_clear()
    get_pool.cache_clear()
    get_checkpointer.cache_clear()
    get_store.cache_clear()
