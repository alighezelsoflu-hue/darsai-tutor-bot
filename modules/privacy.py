"""🗑 Delete my data: remove a student from every table and every in-memory store, in every chat.

On PostgreSQL, delete_student() deletes the student's rows from every darsai_* table that has a user_id
column, found when it runs, so a table added later (and the old darsai_math_progress, still in production)
is covered without changing this file. All in one transaction: either everything goes or nothing does.
Afterwards the student is new to the bot (no darsai_first_seen row, setup not done).

Without a database, the same happens in the in-memory stores (_MEMORY_STORES). A test checks that every
module-level fallback dict is listed there.

What is stored, and why, is in docs/data-inventory.md. The per-process caches with user ids are cleared by
ui/privacy.py, which can import the screens' modules.

All functions are blocking. Call them with asyncio.to_thread.
"""

import logging
import threading
from typing import Callable, Dict, List, Tuple

from psycopg import sql

from modules import activity, ai, input_mode, notify, premium, student
from modules.db import connection, db_configured
from modules.math import shared

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()

# Every in-memory fallback dict, with how to find the user id in its keys.
_MEMORY_STORES: Tuple[Tuple[str, Dict, Callable], ...] = (
    ("ai._MEMORY_FALLBACK", ai._MEMORY_FALLBACK, lambda key: key[1]),            # (chat_id, user_id, topic)
    ("ai._USAGE_FALLBACK", ai._USAGE_FALLBACK, lambda key: key[0]),              # (user_id, day)
    ("student._FALLBACK", student._FALLBACK, lambda key: key),                   # user_id
    ("input_mode._FALLBACK", input_mode._FALLBACK, lambda key: key[1]),          # (chat_id, user_id)
    ("activity._FALLBACK", activity._FALLBACK, lambda key: key[1]),              # (day, user_id)
    ("activity._FIRST_SEEN", activity._FIRST_SEEN, lambda key: key),             # user_id
    ("premium._FALLBACK", premium._FALLBACK, lambda key: key[0]),                # (user_id, choice)
    ("notify._FALLBACK", notify._FALLBACK, lambda key: key[0]),                  # (user_id, course)
    ("shared.MASTERY_FALLBACK", shared.MASTERY_FALLBACK, lambda key: key[0]),    # (user_id, level, topic)
    ("shared.ACTIVE_QUESTION_FALLBACK", shared.ACTIVE_QUESTION_FALLBACK, lambda key: key[1]),  # (chat_id, user_id)
)


def personal_tables(cur) -> List[str]:
    """Every darsai_* table with a user_id column."""
    cur.execute("""
        SELECT table_name FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name LIKE 'darsai%' AND column_name = 'user_id'
        ORDER BY table_name
    """)
    return [row[0] for row in cur.fetchall()]


def delete_student(user_id: int) -> Dict[str, int]:
    """Delete everything stored about the student. Returns {table or store: rows deleted} (only those with rows)."""
    deleted: Dict[str, int] = {}
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            for table in personal_tables(cur):
                cur.execute(sql.SQL("DELETE FROM {} WHERE user_id = %s").format(sql.Identifier(table)), (user_id,))
                if cur.rowcount:
                    deleted[table] = cur.rowcount
    else:
        with _LOCK:
            for name, store, user_of in _MEMORY_STORES:
                keys = [key for key in list(store) if user_of(key) == user_id]
                for key in keys:
                    store.pop(key, None)
                if keys:
                    deleted[name] = len(keys)
    # Counts only, never the content.
    logger.info("Deleted the data of user id %s: %s", user_id, deleted or "nothing was stored")
    return deleted
