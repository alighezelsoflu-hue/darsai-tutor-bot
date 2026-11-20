"""Shared PostgreSQL connection pool.

All database helpers in DarsAI are synchronous. Telegram handlers must call them
through ``asyncio.to_thread`` so a slow query never blocks the event loop.
"""

import logging
import threading
from contextlib import contextmanager
from typing import Iterator, Optional

from config import DATABASE_URL, DB_POOL_MAX_SIZE

try:
    import psycopg  # noqa: F401
    from psycopg_pool import ConnectionPool
except Exception:  # pragma: no cover - local env may not have psycopg installed
    ConnectionPool = None

logger = logging.getLogger(__name__)

_pool: Optional["ConnectionPool"] = None
_pool_lock = threading.Lock()


def db_configured() -> bool:
    return bool(DATABASE_URL and ConnectionPool is not None)


def _get_pool() -> "ConnectionPool":
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ConnectionPool(
                    DATABASE_URL,
                    min_size=1,
                    max_size=max(1, DB_POOL_MAX_SIZE),
                    # Hosted Postgres (e.g. Neon) closes idle connections; check before reuse.
                    check=getattr(ConnectionPool, "check_connection", None),
                    open=True,
                )
    return _pool


@contextmanager
def connection() -> Iterator["psycopg.Connection"]:
    """Borrow a pooled connection. Commits on success, rolls back on error."""
    with _get_pool().connection() as conn:
        yield conn


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None
            logger.info("Database pool closed.")
