"""🔔 Notify me: which students want to hear when a coming-soon course is ready.

One row per student and course in darsai_course_notify, with the student's interface language, so the
announcement can later be sent in that language. /stats counts them per course.

All functions are blocking. Call them with asyncio.to_thread.
"""

import threading
import time
from typing import Dict, Iterable, Tuple

from modules.courses import COMING_SOON
from modules.db import connection, db_configured

# In-memory fallback, used only when DATABASE_URL is not set: {(user_id, course): {"language", "created_at"}}
_FALLBACK: Dict[Tuple[int, str], Dict] = {}
_LOCK = threading.Lock()


def init_notify_db() -> None:
    if not db_configured():
        return
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS darsai_course_notify (
                user_id BIGINT NOT NULL,
                course TEXT NOT NULL,
                language TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY(user_id, course)
            );
        """)


def wants_notice(user_id: int, course: str) -> bool:
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM darsai_course_notify WHERE user_id=%s AND course=%s", (user_id, course))
            return cur.fetchone() is not None
    with _LOCK:
        return (user_id, course) in _FALLBACK


def add_notice(user_id: int, course: str, language: str) -> None:
    """Save that the student wants to hear when the course is ready. Doing it again changes nothing."""
    if course not in COMING_SOON:
        raise ValueError(f"Not a coming-soon course: {course!r}")
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO darsai_course_notify (user_id, course, language) VALUES (%s, %s, %s)
                ON CONFLICT (user_id, course) DO NOTHING
            """, (user_id, course, language))
        return
    with _LOCK:
        _FALLBACK.setdefault((user_id, course), {"language": language, "created_at": time.time()})


def notice_summary(exclude: Iterable[int] = ()) -> Dict:
    """{"students": n, "courses": {course: students}} for /stats, every coming-soon course in course order.

    Students in exclude (admins) are left out, and so are rows for courses no longer in the course list
    (they are kept in the table: Astrology's, from before Biology replaced it).
    """
    exclude = sorted(set(exclude))
    current = list(COMING_SOON)
    if db_configured():
        params = {"exclude": exclude, "courses": current}
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT course, COUNT(*) FROM darsai_course_notify
                WHERE user_id <> ALL(%(exclude)s::bigint[]) AND course = ANY(%(courses)s::text[]) GROUP BY course
            """, params)
            courses = dict(cur.fetchall())
            cur.execute("""
                SELECT COUNT(DISTINCT user_id) FROM darsai_course_notify
                WHERE user_id <> ALL(%(exclude)s::bigint[]) AND course = ANY(%(courses)s::text[])
            """, params)
            students = cur.fetchone()[0]
    else:
        with _LOCK:
            keys = [(uid, course) for (uid, course) in _FALLBACK if uid not in exclude and course in current]
        courses = {}
        for _, course in keys:
            courses[course] = courses.get(course, 0) + 1
        students = len({uid for uid, _ in keys})
    return {"students": students, "courses": {course: courses.get(course, 0) for course in COMING_SOON}}
