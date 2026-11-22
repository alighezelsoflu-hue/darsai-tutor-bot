"""Settings that belong to a student in every chat (interface language and math level), whether they have
answered the setup questions, and which bottom keyboard they have been told about.

All functions are blocking. Call them with asyncio.to_thread.
"""

from typing import Dict

from modules.db import connection, db_configured

# In-memory fallback, used only when DATABASE_URL is not set.
_FALLBACK: Dict[int, Dict] = {}


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


def init_setup_db() -> None:
    """Call after every other init_*_db. Adds setup_done and keyboard_version to darsai_student.

    When it adds them, every student the bot already knows (any table with students in it) is marked as set
    up, so only students who are new from then on get the setup questions.
    """
    if not db_configured():
        return
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = 'darsai_student' AND column_name = 'setup_done'
            )
        """)
        if cur.fetchone()[0]:
            return
        cur.execute("""
            ALTER TABLE darsai_student
                ADD COLUMN IF NOT EXISTS setup_done BOOLEAN NOT NULL DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS keyboard_version INTEGER NOT NULL DEFAULT 0;
        """)
        cur.execute("""
            INSERT INTO darsai_student (user_id, setup_done)
            SELECT user_id, TRUE FROM (
                SELECT user_id FROM darsai_first_seen
                UNION SELECT user_id FROM darsai_student
                UNION SELECT user_id FROM darsai_user_profile
                UNION SELECT user_id FROM darsai_mastery
                UNION SELECT user_id FROM darsai_ai_messages
                UNION SELECT user_id FROM darsai_ai_usage
                UNION SELECT user_id FROM darsai_daily_activity
                UNION SELECT user_id FROM darsai_premium_waitlist
            ) AS known
            ON CONFLICT (user_id) DO UPDATE SET setup_done = TRUE;
        """)


def get_student(user_id: int) -> Dict:
    """The student's saved settings. language and level are None until the student chooses them."""
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT language, level, setup_done, keyboard_version FROM darsai_student WHERE user_id=%s", (user_id,)
            )
            row = cur.fetchone()
        if row:
            return {"language": row[0], "level": row[1], "setup_done": bool(row[2]), "keyboard_version": int(row[3])}
        return {"language": None, "level": None, "setup_done": False, "keyboard_version": 0}
    saved = _FALLBACK.get(user_id, {})
    return {
        "language": saved.get("language"),
        "level": saved.get("level"),
        "setup_done": bool(saved.get("setup_done")),
        "keyboard_version": int(saved.get("keyboard_version", 0)),
    }


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


def finish_setup(user_id: int, keyboard_version: int) -> bool:
    """Mark the setup questions as answered (the message that ends them brings the bottom keyboard).

    Returns True only for the call that finished it, so a second tap on an old setup button can tell.
    """
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO darsai_student (user_id, setup_done, keyboard_version) VALUES (%s, TRUE, %s)
                ON CONFLICT (user_id) DO UPDATE
                SET setup_done=TRUE, keyboard_version=GREATEST(darsai_student.keyboard_version, EXCLUDED.keyboard_version),
                    updated_at=NOW()
                WHERE NOT darsai_student.setup_done
            """, (user_id, keyboard_version))
            return cur.rowcount > 0
    saved = _FALLBACK.setdefault(user_id, {})
    if saved.get("setup_done"):
        return False
    saved["setup_done"] = True
    saved["keyboard_version"] = max(int(saved.get("keyboard_version", 0)), keyboard_version)
    return True


def claim_keyboard_version(user_id: int, version: int, only_set_up: bool = True) -> bool:
    """Note that the student now has bottom keyboard `version`. True only when this call changed it.

    With only_set_up, students who haven't answered the setup questions are left alone (finishing them
    brings the keyboard). One UPDATE, so two updates at the same moment can't both send the notice.
    """
    condition = "AND setup_done" if only_set_up else ""
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute(f"""
                UPDATE darsai_student SET keyboard_version=%s, updated_at=NOW()
                WHERE user_id=%s AND keyboard_version < %s {condition}
            """, (version, user_id, version))
            return cur.rowcount > 0
    saved = _FALLBACK.get(user_id)
    if saved is None or int(saved.get("keyboard_version", 0)) >= version:
        return False
    if only_set_up and not saved.get("setup_done"):
        return False
    saved["keyboard_version"] = version
    return True
