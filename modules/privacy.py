"""🗑 Delete my data: remove a student from every table and every in-memory store, in every chat.

On PostgreSQL, delete_student() deletes the student's rows from every darsai_* table that has a user_id
column, found when it runs, so a table added later (and the old darsai_math_progress, still in production)
is covered without changing this file. All in one transaction: either everything goes or nothing does.
Afterwards the student is new to the bot (no darsai_first_seen row, setup not done).

Without a database, the same happens in the in-memory stores (_MEMORY_STORES). A test checks that every
module-level fallback dict is listed there.

One thing is kept on purpose: today's tutor-message count (darsai_ai_usage for today's UTC day, the day
reserve_ai_message charges). Without it, deleting would reset the daily limit, and a student could delete
again and again for unlimited tutor messages. Once the day is over, drop_kept_usage() removes it: it deletes
past days' usage rows of students with no darsai_first_seen row, which after a delete is exactly them (anyone
who uses the bot again gets a first-seen row again). It runs at startup and after every delete; in memory the
old days go by themselves (reserve_ai_message drops them).

What is stored, and why, is in docs/data-inventory.md. The per-process caches with user ids are cleared by
ui/privacy.py, which can import the screens' modules.

All functions are blocking. Call them with asyncio.to_thread.
"""

import logging
import threading
from typing import Callable, Dict, List, Tuple

from psycopg import sql

from modules import activity, ai, input_mode, miniapp, notify, premium, student
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
    ("miniapp._FALLBACK", miniapp._FALLBACK, lambda key: key[0]),                # (user_id, n)
)


def personal_tables(cur) -> List[str]:
    """Every darsai_* table with a user_id column."""
    cur.execute("""
        SELECT table_name FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name LIKE 'darsai%' AND column_name = 'user_id'
        ORDER BY table_name
    """)
    return [row[0] for row in cur.fetchall()]


# The table with today's tutor-message count, which a delete keeps until the day is over.
USAGE_TABLE = "darsai_ai_usage"


def _drop_kept_usage(cur, today) -> int:
    cur.execute("""
        DELETE FROM darsai_ai_usage AS u
        WHERE u.day < %s AND NOT EXISTS (SELECT 1 FROM darsai_first_seen AS f WHERE f.user_id = u.user_id)
    """, (today,))
    return cur.rowcount


def drop_kept_usage() -> int:
    """Delete the past days' tutor-message counts that deletes kept (see the module docstring). Startup calls it."""
    if not db_configured():
        return 0
    with connection() as conn, conn.cursor() as cur:
        dropped = _drop_kept_usage(cur, ai._today())
    if dropped:
        logger.info("Removed %d tutor-message counts kept by Delete my data on earlier days.", dropped)
    return dropped


def delete_student(user_id: int) -> Dict[str, int]:
    """Delete everything stored about the student but today's tutor-message count.

    Returns {table or store: rows deleted} (only those with rows).
    """
    deleted: Dict[str, int] = {}
    today = ai._today()
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            for table in personal_tables(cur):
                query = sql.SQL("DELETE FROM {} WHERE user_id = %s").format(sql.Identifier(table))
                params = (user_id,)
                if table == USAGE_TABLE:
                    query = sql.SQL("DELETE FROM {} WHERE user_id = %s AND day <> %s").format(sql.Identifier(table))
                    params = (user_id, today)
                cur.execute(query, params)
                if cur.rowcount:
                    deleted[table] = cur.rowcount
            _drop_kept_usage(cur, today)
    else:
        with _LOCK:
            for name, store, user_of in _MEMORY_STORES:
                keys = [key for key in list(store) if user_of(key) == user_id]
                if store is ai._USAGE_FALLBACK:
                    keys = [key for key in keys if key[1] != today]
                for key in keys:
                    store.pop(key, None)
                if keys:
                    deleted[name] = len(keys)
    # Counts only, never the content.
    logger.info("Deleted the data of user id %s: %s", user_id, deleted or "nothing was stored")
    return deleted
