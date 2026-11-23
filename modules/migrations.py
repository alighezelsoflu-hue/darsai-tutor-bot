"""The database schema, as numbered migrations. migrate() runs at every startup and applies the ones a database
hasn't had yet, in order.

- darsai_schema_version has one row per applied migration (version, name, when).
- Each migration runs in its own transaction holding a PostgreSQL advisory lock (pg_advisory_xact_lock), and
  checks again that it hasn't been applied once it has the lock. So two instances starting together (old and
  new during a deploy) can't apply one twice, and a failed migration leaves nothing half done: startup stops
  with the error and the next start tries again. Transaction-level locks also work through Neon's pooler.
- Once it has the advisory lock, a migration waits at most MIGRATION_LOCK_TIMEOUT_SECONDS for any table lock.
  An ALTER TABLE waiting behind a long query would otherwise make every later query on that table wait
  behind it. With the timeout the migration fails fast and rolls back, the deploy fails while the old
  instance keeps serving, and the next start tries again.
- Migration 1 is the schema as it was when migrations started (2026-11-22): every CREATE TABLE and ADD
  COLUMN from the old init_*_db functions, with their "only the first time" backfills. It brings a database of
  any older version fully up to date (e.g. one without darsai_first_seen or setup_done), and on production it
  only records version 1. Its copy of the old darsai_math_progress counts runs with it, once ever.
- Never change a migration once it is on main: databases that have it won't run it again. Change the schema
  with a new migration at the end of MIGRATIONS.

Blocking. main.init_databases() calls migrate() at startup (with asyncio.to_thread).
"""

import logging
from typing import Callable, List, Optional, Tuple

import config
from modules.db import connection, db_configured

logger = logging.getLogger(__name__)

# Any fixed number: the advisory lock only DarsAI's migrations take.
LOCK_KEY = 7_301_224_001


# ------------------------------------------------------------
# Migration 1: the baseline
# ------------------------------------------------------------

def _ai_tables(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS darsai_ai_messages (
            id BIGSERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            topic TEXT NOT NULL DEFAULT 'general',
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_darsai_ai_messages_lookup
        ON darsai_ai_messages (chat_id, user_id, topic, id DESC);
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS darsai_ai_usage (
            user_id BIGINT NOT NULL,
            day DATE NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(user_id, day)
        );
    """)


def _math_tables(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS darsai_user_profile (
            chat_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            level TEXT NOT NULL DEFAULT 'high_school',
            language TEXT NOT NULL DEFAULT 'en',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY(chat_id, user_id)
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS darsai_mastery (
            user_id BIGINT NOT NULL,
            level TEXT NOT NULL,
            topic TEXT NOT NULL,
            mastery DOUBLE PRECISION NOT NULL DEFAULT 0,
            correct_count INTEGER NOT NULL DEFAULT 0,
            wrong_count INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY(user_id, level, topic)
        );
    """)
    _copy_old_progress(cur)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS darsai_active_question (
            chat_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            question JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY(chat_id, user_id)
        );
    """)


def _copy_old_progress(cur) -> None:
    """Copy counts from darsai_math_progress (per chat, before mastery existed) into darsai_mastery.

    Mastery is estimated as if every old answer was a medium question. Topics a student already has in
    darsai_mastery are left alone. It runs with migration 1, once ever, so progress a student deleted can't
    come back from this table.
    """
    cur.execute("SELECT to_regclass('darsai_math_progress') IS NOT NULL")
    if not cur.fetchone()[0]:
        return
    cur.execute("""
        INSERT INTO darsai_mastery (user_id, level, topic, mastery, correct_count, wrong_count)
        SELECT user_id, level, topic,
               CASE WHEN SUM(correct_count + wrong_count) = 0 THEN 0
                    ELSE 0.85 * SUM(correct_count)::float / SUM(correct_count + wrong_count)
                         * (1 - power(0.7::float, LEAST(SUM(correct_count + wrong_count), 50)::float))
               END,
               SUM(correct_count), SUM(wrong_count)
        FROM darsai_math_progress
        GROUP BY user_id, level, topic
        ON CONFLICT (user_id, level, topic) DO NOTHING;
    """)


def _student_table(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS darsai_student (
            user_id BIGINT PRIMARY KEY,
            language TEXT,
            level TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)


def _input_mode_table(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS darsai_input_mode (
            chat_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            state JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY(chat_id, user_id)
        );
    """)


def _activity_table(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS darsai_daily_activity (
            day DATE NOT NULL,
            user_id BIGINT NOT NULL,
            practice_answers INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(day, user_id)
        );
    """)


def _premium_table(cur) -> None:
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


def _notify_table(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS darsai_course_notify (
            user_id BIGINT NOT NULL,
            course TEXT NOT NULL,
            language TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY(user_id, course)
        );
    """)


def _first_seen_table(cur) -> None:
    """After the other tables. When it creates darsai_first_seen, it first copies in every student the other
    tables know, with the earliest time they show, so existing students don't count as new.
    """
    cur.execute("SELECT to_regclass('darsai_first_seen') IS NOT NULL")
    if cur.fetchone()[0]:
        return
    cur.execute("""
        CREATE TABLE IF NOT EXISTS darsai_first_seen (
            user_id BIGINT PRIMARY KEY,
            source TEXT,
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    cur.execute("""
        INSERT INTO darsai_first_seen (user_id, source, first_seen_at)
        SELECT user_id, NULL, MIN(seen) FROM (
            SELECT user_id, created_at AS seen FROM darsai_ai_messages
            UNION ALL SELECT user_id, day::timestamp AT TIME ZONE 'UTC' FROM darsai_ai_usage
            UNION ALL SELECT user_id, updated_at FROM darsai_mastery
            UNION ALL SELECT user_id, created_at FROM darsai_student
            UNION ALL SELECT user_id, created_at FROM darsai_user_profile
            UNION ALL SELECT user_id, day::timestamp AT TIME ZONE 'UTC' FROM darsai_daily_activity
            UNION ALL SELECT user_id, created_at FROM darsai_premium_waitlist
        ) AS known
        GROUP BY user_id
        ON CONFLICT (user_id) DO NOTHING;
    """)


def _setup_columns(cur) -> None:
    """Last. Adds setup_done and keyboard_version to darsai_student. When it adds them, every student any table
    knows is marked as set up, so only students who are new from then on get the setup questions.
    """
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


def _baseline(cur) -> None:
    """Every table as of 2026-11-22, in the order the old init_*_db functions ran at startup."""
    _ai_tables(cur)
    _math_tables(cur)
    _student_table(cur)
    _input_mode_table(cur)
    _activity_table(cur)
    _premium_table(cur)
    _notify_table(cur)
    _first_seen_table(cur)
    _setup_columns(cur)


# ------------------------------------------------------------
# Migration 2: the Mini App reachability test
# ------------------------------------------------------------

def _miniapp_ping_table(cur) -> None:
    """Each open of the Mini App (its load timings), and each "❌ It didn't open" (modules/miniapp.py)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS darsai_miniapp_ping (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            day DATE NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            opened BOOLEAN NOT NULL,
            platform TEXT,
            bridge BOOLEAN,
            dns_ms INTEGER,
            connect_ms INTEGER,
            ttfb_ms INTEGER,
            dom_ms INTEGER,
            total_ms INTEGER,
            api_ms INTEGER
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_darsai_miniapp_ping_day ON darsai_miniapp_ping (day);")


# ------------------------------------------------------------
# The list
# ------------------------------------------------------------

# (version, name, function taking a cursor). Versions go up by one. Add new ones at the end; never edit one
# that is on main.
MIGRATIONS: List[Tuple[int, str, Callable]] = [
    (1, "baseline: every table as of 2026-11-22", _baseline),
    (2, "Mini App reachability test: darsai_miniapp_ping", _miniapp_ping_table),
]

LATEST_VERSION = MIGRATIONS[-1][0]


def _version_table() -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
        cur.execute("""
            CREATE TABLE IF NOT EXISTS darsai_schema_version (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)


def schema_version() -> int:
    """The highest migration applied to the database (0: none)."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(version), 0) FROM darsai_schema_version")
        return cur.fetchone()[0]


def _apply(version: int, name: str, migration: Callable) -> bool:
    """Apply one migration in its own transaction, under the lock. False if another instance applied it first."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
        # After the advisory lock (another instance's migration may take longer), for this transaction only.
        cur.execute("SELECT set_config('lock_timeout', %s, true)", (f"{config.MIGRATION_LOCK_TIMEOUT_SECONDS}s",))
        cur.execute("SELECT 1 FROM darsai_schema_version WHERE version = %s", (version,))
        if cur.fetchone():
            return False
        migration(cur)
        cur.execute("INSERT INTO darsai_schema_version (version, name) VALUES (%s, %s)", (version, name))
    return True


def migrate() -> Optional[int]:
    """Apply every migration the database doesn't have yet. Returns the schema version (None: no database)."""
    if not db_configured():
        logger.info("No database (DATABASE_URL is empty): everything is kept in memory and lost on restart.")
        return None
    _version_table()
    current = schema_version()
    for version, name, migration in MIGRATIONS:
        if version <= current:
            continue
        if _apply(version, name, migration):
            logger.info("Database migration %d applied: %s", version, name)
    current = schema_version()
    if current > LATEST_VERSION:
        # A newer deploy migrated the database (e.g. during a rollback). Its tables still work for this code
        # only if that migration kept them compatible, so say so loudly.
        logger.warning("Database schema version %d is newer than this code knows (%d).", current, LATEST_VERSION)
    logger.info("Database schema version %d.", current)
    return current
