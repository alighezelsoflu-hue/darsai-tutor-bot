"""Which students used the bot on which day, how many practice questions they finished that day, and when
the bot first saw each student (with the start link they came from).

- darsai_daily_activity: one row per student per UTC day. /stats counts active students and practice
  answers per day from it.
- darsai_first_seen: one row per student, written the first time the bot sees them. `source` is the
  payload of the start link they opened (t.me/<bot>?start=<source>), or NULL. It is never changed later,
  so only new students get a source.

No Telegram imports, so modules/math/shared.py can use it.

All functions are blocking. Call them with asyncio.to_thread.
"""

import re
import threading
from datetime import date, datetime, timezone
from typing import Dict, Optional, Tuple

from modules.db import connection, db_configured

# In-memory fallback, used only when DATABASE_URL is not set: {(day, user_id): {"practice_answers": n}}
_FALLBACK: Dict[Tuple[date, int], Dict[str, int]] = {}
# {user_id: {"source": str or None, "at": datetime (UTC)}}
_FIRST_SEEN: Dict[int, Dict] = {}
_LOCK = threading.Lock()

# What Telegram allows in a start link's payload.
_SOURCE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def valid_source(payload: Optional[str]) -> Optional[str]:
    """The start-link source, or None when the payload isn't one (anyone can type "/start <anything>")."""
    return payload if payload and _SOURCE.fullmatch(payload) else None


def utc_today() -> date:
    """Days are UTC, like the daily tutor limit."""
    return datetime.now(timezone.utc).date()


def mark_active(user_id: int, day: Optional[date] = None, source: Optional[str] = None) -> None:
    """Note that the student used the bot today. Doing it again the same day changes nothing.

    The first time the bot ever sees the student, it also saves when, and the start-link source if any.
    """
    day = day or utc_today()
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO darsai_daily_activity (day, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (day, user_id),
            )
            cur.execute(
                "INSERT INTO darsai_first_seen (user_id, source) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, source),
            )
        return
    with _LOCK:
        _FALLBACK.setdefault((day, user_id), {"practice_answers": 0})
        _FIRST_SEEN.setdefault(user_id, {"source": source, "at": datetime.now(timezone.utc)})


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
