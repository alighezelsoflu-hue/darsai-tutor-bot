"""Settings that belong to a student in every chat (interface language and math level).

All functions are blocking. Call them with asyncio.to_thread.
"""

from typing import Dict, Optional

from modules.db import connection, db_configured

# In-memory fallback, used only when DATABASE_URL is not set.
_FALLBACK: Dict[int, Dict[str, str]] = {}


def init_student_db() -> None:
    if not db_configured():
        return
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS darsai_student (
                user_id BIGINT PRIMARY KEY,
                language TEXT,
                level TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)


def get_student(user_id: int) -> Dict[str, Optional[str]]:
    """The student's saved settings. A value is None until the student chooses it."""
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT language, level FROM darsai_student WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
        return {"language": row[0], "level": row[1]} if row else {"language": None, "level": None}
    saved = _FALLBACK.get(user_id, {})
    return {"language": saved.get("language"), "level": saved.get("level")}


def set_language(user_id: int, language: str) -> None:
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO darsai_student (user_id, language) VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET language=EXCLUDED.language, updated_at=NOW();
            """, (user_id, language))
        return
    _FALLBACK.setdefault(user_id, {})["language"] = language


def set_level(user_id: int, level: str) -> None:
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO darsai_student (user_id, level) VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET level=EXCLUDED.level, updated_at=NOW();
            """, (user_id, level))
        return
    _FALLBACK.setdefault(user_id, {})["level"] = level
