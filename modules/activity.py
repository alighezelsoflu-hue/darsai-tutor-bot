"""Which students used the bot on which day, and how many practice questions they finished that day.

One row per student per UTC day in darsai_daily_activity. /stats counts active students and practice
answers per day from it. No Telegram imports, so modules/math/shared.py can use it.

All functions are blocking. Call them with asyncio.to_thread.
"""

import threading
from datetime import date, datetime, timezone
from typing import Dict, Optional, Tuple

from modules.db import connection, db_configured

# In-memory fallback, used only when DATABASE_URL is not set: {(day, user_id): {"practice_answers": n}}
_FALLBACK: Dict[Tuple[date, int], Dict[str, int]] = {}
_LOCK = threading.Lock()


def utc_today() -> date:
    """Days are UTC, like the daily tutor limit."""
    return datetime.now(timezone.utc).date()


def init_activity_db() -> None:
    if not db_configured():
        return
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS darsai_daily_activity (
                day DATE NOT NULL,
                user_id BIGINT NOT NULL,
                practice_answers INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(day, user_id)
            );
        """)


def mark_active(user_id: int, day: Optional[date] = None) -> None:
    """Note that the student used the bot today. Doing it again the same day changes nothing."""
    day = day or utc_today()
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO darsai_daily_activity (day, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (day, user_id),
            )
        return
    with _LOCK:
        _FALLBACK.setdefault((day, user_id), {"practice_answers": 0})


def add_practice_answer(user_id: int, cur=None) -> None:
    """Count one finished practice question for today (it also makes the student active today).

    Pass the cursor of an open transaction to count it in that transaction (record_answer does).
    """
    day = utc_today()
    sql = """
        INSERT INTO darsai_daily_activity (day, user_id, practice_answers) VALUES (%s, %s, 1)
        ON CONFLICT (day, user_id)
        DO UPDATE SET practice_answers = darsai_daily_activity.practice_answers + 1;
    """
    if cur is not None:
        cur.execute(sql, (day, user_id))
        return
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute(sql, (day, user_id))
        return
    with _LOCK:
        _FALLBACK.setdefault((day, user_id), {"practice_answers": 0})["practice_answers"] += 1
