"""The Premium waitlist: what each student would want most from Premium.

A student is on the waitlist while they have at least one pick. Each pick is a row in
darsai_premium_waitlist with where it was made (the 💎 Premium screen or the daily-limit message) and
the student's interface language, so the announcement can later be sent in that language.

All functions are blocking. Call them with asyncio.to_thread.
"""

import threading
import time
from typing import Dict, List, Tuple

from modules.db import connection, db_configured

# In the order the buttons show them.
CHOICES = ("konkur", "msgs", "photo", "plan", "ai")
SOURCES = ("menu", "limit")

# In-memory fallback, used only when DATABASE_URL is not set: {(user_id, choice): {"source", "language", "created_at"}}
_FALLBACK: Dict[Tuple[int, str], Dict] = {}
_LOCK = threading.Lock()


def init_premium_db() -> None:
    if not db_configured():
        return
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS darsai_premium_waitlist (
                user_id BIGINT NOT NULL,
                choice TEXT NOT NULL,
                source TEXT NOT NULL,
                language TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY(user_id, choice)
            );
        """)


def _ordered(choices) -> List[str]:
    picked = set(choices)
    return [choice for choice in CHOICES if choice in picked]


def get_choices(user_id: int) -> List[str]:
    """The student's picks, in button order. Empty means they are not on the waitlist."""
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT choice FROM darsai_premium_waitlist WHERE user_id=%s", (user_id,))
            return _ordered(row[0] for row in cur.fetchall())
    with _LOCK:
        return _ordered(choice for (uid, choice) in _FALLBACK if uid == user_id)


def set_choice(user_id: int, choice: str, picked: bool, source: str, language: str) -> List[str]:
    """Add or remove one pick. Doing the same again changes nothing. Returns the student's picks afterwards."""
    if choice not in CHOICES or source not in SOURCES:
        raise ValueError(f"Unknown Premium choice or source: {choice!r}, {source!r}")
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            if picked:
                cur.execute("""
                    INSERT INTO darsai_premium_waitlist (user_id, choice, source, language) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, choice) DO NOTHING
                """, (user_id, choice, source, language))
            else:
                cur.execute("DELETE FROM darsai_premium_waitlist WHERE user_id=%s AND choice=%s", (user_id, choice))
            cur.execute("SELECT choice FROM darsai_premium_waitlist WHERE user_id=%s", (user_id,))
            return _ordered(row[0] for row in cur.fetchall())
    with _LOCK:
        if picked:
            _FALLBACK.setdefault((user_id, choice), {"source": source, "language": language, "created_at": time.time()})
        else:
            _FALLBACK.pop((user_id, choice), None)
        return _ordered(c for (uid, c) in _FALLBACK if uid == user_id)


def waitlist_summary() -> Dict:
    """{"students": n, "sources": {source: students}, "choices": {choice: students}} for /stats.

    A student's source is where they made their first pick.
    """
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(DISTINCT user_id) FROM darsai_premium_waitlist")
            students = cur.fetchone()[0]
            cur.execute("SELECT choice, COUNT(*) FROM darsai_premium_waitlist GROUP BY choice")
            choices = dict(cur.fetchall())
            cur.execute("""
                SELECT source, COUNT(*) FROM (
                    SELECT DISTINCT ON (user_id) user_id, source FROM darsai_premium_waitlist
                    ORDER BY user_id, created_at, choice
                ) AS first_pick
                GROUP BY source
            """)
            sources = dict(cur.fetchall())
    else:
        with _LOCK:
            rows = [(uid, choice, dict(row)) for (uid, choice), row in _FALLBACK.items()]
        first: Dict[int, Tuple[float, str]] = {}
        choices = {}
        for uid, choice, row in rows:
            choices[choice] = choices.get(choice, 0) + 1
            if uid not in first or row["created_at"] < first[uid][0]:
                first[uid] = (row["created_at"], row["source"])
        students = len(first)
        sources = {}
        for _, source in first.values():
            sources[source] = sources.get(source, 0) + 1
    return {
        "students": students,
        "sources": {source: sources.get(source, 0) for source in SOURCES},
        "choices": {choice: choices.get(choice, 0) for choice in CHOICES},
    }
