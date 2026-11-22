"""The SQL against a real PostgreSQL. Skipped unless TEST_DATABASE_URL is set.

Every test starts by dropping all darsai_* tables, so TEST_DATABASE_URL must name a database whose name contains
"test" (the tests refuse to run otherwise). Never point it at production.

CI runs these against a PostgreSQL service (.github/workflows/tests.yml). Locally, with a throwaway server
created with `initdb -E UTF8 --locale=C` (the tests refuse a server that isn't UTF-8):
    TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/darsai_test python -m unittest tests.test_postgres
"""

import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import urlparse

import main
from modules import activity, ai, db, input_mode, migrations, notify, premium, stats, student
from modules.db import connection
from modules.i18n import t
from modules.math import shared
from modules.ui import home, router, setup, typed
from tests.test_ui import STUDENT, TelegramMocks, button_update, run, text_update

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()

ALL_TABLES = {
    "darsai_ai_messages", "darsai_ai_usage", "darsai_student", "darsai_user_profile", "darsai_mastery",
    "darsai_active_question", "darsai_input_mode", "darsai_daily_activity", "darsai_premium_waitlist",
    "darsai_course_notify", "darsai_first_seen", "darsai_schema_version",
}


def older_database(first_seen: bool = True, setup_columns: bool = True) -> None:
    """A database as a version from before migrations left it: no darsai_schema_version, and without the parts
    added later (darsai_first_seen came with the start links, the setup columns with the course home).
    """
    with connection() as conn, conn.cursor() as cur:
        migrations._baseline(cur)
        if not setup_columns:
            cur.execute("ALTER TABLE darsai_student DROP COLUMN setup_done, DROP COLUMN keyboard_version")
        if not first_seen:
            cur.execute("DROP TABLE darsai_first_seen")


def execute(sql: str, params=()):
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else None


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL is not set")
class PostgresTests(TelegramMocks):
    @classmethod
    def setUpClass(cls):
        name = urlparse(TEST_DATABASE_URL).path.lstrip("/")
        if "test" not in name.lower():
            raise RuntimeError(f"TEST_DATABASE_URL must name a test database (its name must contain 'test'), not {name!r}.")
        cls._database = patch.object(db, "DATABASE_URL", TEST_DATABASE_URL)
        cls._database.start()
        (encoding,) = execute("SHOW server_encoding")[0]
        encoding = encoding.decode() if isinstance(encoding, bytes) else encoding
        if encoding.upper() not in ("UTF8", "UTF-8"):
            db.close_pool()
            cls._database.stop()
            raise RuntimeError(
                f"The test database's server encoding is {encoding}, not UTF8, so text comes back as bytes and every "
                "test would fail. Create the server with: initdb -E UTF8 --locale=C …"
            )

    @classmethod
    def tearDownClass(cls):
        db.close_pool()
        cls._database.stop()

    def setUp(self):
        super().setUp()
        self.assertTrue(db.db_configured())
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = current_schema() AND tablename LIKE 'darsai%%'")
            for (table,) in cur.fetchall():
                cur.execute(f'DROP TABLE "{table}" CASCADE')

    def tables(self):
        rows = execute("SELECT tablename FROM pg_tables WHERE schemaname = current_schema() AND tablename LIKE 'darsai%%'")
        return {table for (table,) in rows}

    # ---------------------------------------------------------------- startup

    def test_startup_creates_every_table_and_can_run_again(self):
        with self.assertLogs("modules.migrations", "INFO") as logs:
            main.init_databases()
        self.assertIn("Database migration 1 applied: baseline: every table as of 2026-11-22", logs.output[0])
        self.assertIn("Database schema version 1.", logs.output[-1])
        with self.assertLogs("modules.migrations", "INFO") as logs:
            main.init_databases()
        self.assertEqual(len(logs.output), 1, "nothing to apply the second time")
        self.assertEqual(self.tables(), ALL_TABLES)
        self.assertEqual(execute("SELECT COUNT(*) FROM darsai_student"), [(0,)])
        self.assertEqual(execute("SELECT version, name FROM darsai_schema_version"), [(1, "baseline: every table as of 2026-11-22")])

    def test_production_today_only_records_version_1(self):
        older_database()  # the schema production has now, without darsai_schema_version
        student.set_language(1, "fa")
        student.finish_setup(1, 1)
        student.set_language(2, "en")  # a new student in the middle of setup
        shared.record_answer(1, "high_school", "algebra", "easy", "first_try")
        activity.mark_active(3, source="insta")
        before = {table: execute(f"SELECT COUNT(*) FROM {table}") for table in ALL_TABLES - {"darsai_schema_version"}}
        main.init_databases()
        self.assertEqual(migrations.schema_version(), 1)
        self.assertEqual({table: execute(f"SELECT COUNT(*) FROM {table}") for table in before}, before)
        self.assertEqual(student.get_student(2)["setup_done"], False, "still gets the setup questions")
        self.assertEqual(student.get_student(1)["keyboard_version"], 1)

    def test_upgrade_marks_every_known_student_as_set_up(self):
        older_database(setup_columns=False)  # before the course home
        activity.mark_active(1)  # seen by the tracker
        student.set_language(2, "fa")
        shared.record_answer(3, "high_school", "algebra", "easy", "first_try")  # missing from darsai_first_seen
        main.init_databases()
        rows = execute("SELECT user_id, language, setup_done, keyboard_version FROM darsai_student ORDER BY user_id")
        self.assertEqual(rows, [(1, None, True, 0), (2, "fa", True, 0), (3, None, True, 0)])
        # A student who is new after the upgrade gets setup, and a later startup doesn't mark them as done.
        activity.mark_active(10)
        student.set_language(10, "en")
        main.init_databases()
        self.assertFalse(student.get_student(10)["setup_done"])
        self.assertFalse(student.claim_keyboard_version(10, 1), "no notice before setup")
        self.assertTrue(student.finish_setup(10, 1))
        self.assertFalse(student.finish_setup(10, 1))
        self.assertEqual(student.get_student(10), {"language": "en", "level": None, "setup_done": True, "keyboard_version": 1})
        self.assertTrue(student.finish_setup(11, 1), "no row yet")
        # Existing students get the keyboard notice once; /start's welcome counts too.
        self.assertTrue(student.claim_keyboard_version(1, 1))
        self.assertFalse(student.claim_keyboard_version(1, 1))
        self.assertTrue(student.claim_keyboard_version(2, 1, only_set_up=False))
        self.assertFalse(student.claim_keyboard_version(2, 1))

    def test_first_seen_backfill_keeps_the_earliest_time(self):
        older_database(first_seen=False, setup_columns=False)  # before the start links
        today = activity.utc_today()
        execute("INSERT INTO darsai_ai_messages (chat_id, user_id, role, content, created_at) VALUES "
                "(70, 70, 'user', 'hi', NOW() - INTERVAL '30 days'), (70, 70, 'user', 'again', NOW())")
        execute("INSERT INTO darsai_ai_usage (user_id, day, count) VALUES (60, %s, 2)", (today - timedelta(days=2),))
        execute("INSERT INTO darsai_daily_activity (day, user_id) VALUES (%s, 1), (%s, 1)", (today - timedelta(days=5), today))
        execute("INSERT INTO darsai_premium_waitlist (user_id, choice, source, language) VALUES (7, 'photo', 'menu', 'en')")
        main.init_databases()
        rows = {uid: (source, at) for uid, source, at in execute("SELECT user_id, source, first_seen_at FROM darsai_first_seen")}
        self.assertEqual(set(rows), {1, 7, 60, 70})
        self.assertTrue(all(source is None for source, _ in rows.values()))
        midnight = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        self.assertEqual(rows[1][1], midnight - timedelta(days=5))
        self.assertEqual(rows[60][1], midnight - timedelta(days=2))
        self.assertGreater(datetime.now(timezone.utc) - rows[70][1], timedelta(days=29))
        # Start links: only the first source counts, and only for new students.
        activity.mark_active(100, today, "insta")
        activity.mark_active(100, today, "other")
        activity.mark_active(70, today, "insta")
        self.assertEqual(execute("SELECT user_id, source FROM darsai_first_seen WHERE user_id IN (70, 100) ORDER BY user_id"),
                         [(70, None), (100, "insta")])

    def test_old_progress_is_copied_into_mastery_once_ever(self):
        execute("""CREATE TABLE darsai_math_progress (chat_id BIGINT, user_id BIGINT, level TEXT, topic TEXT,
                   correct_count INTEGER, wrong_count INTEGER)""")
        execute("INSERT INTO darsai_math_progress VALUES (1, 5, 'high_school', 'algebra', 3, 1), (2, 5, 'high_school', 'algebra', 1, 0)")
        main.init_databases()
        (entry,) = shared.get_mastery(5).values()
        self.assertEqual((entry["correct"], entry["wrong"]), (4, 1))
        self.assertGreater(entry["mastery"], 0)
        # The student's progress is deleted: later startups never bring it back from the old table.
        execute("DELETE FROM darsai_mastery WHERE user_id = 5")
        main.init_databases()
        self.assertEqual(shared.get_mastery(5), {})

    # ---------------------------------------------------------------- migrations

    def test_two_instances_starting_together_apply_each_migration_once(self):
        errors = []

        def start():
            try:
                migrations.migrate()
            except Exception as error:  # pragma: no cover - shown by the assertion below
                errors.append(error)

        with self.assertLogs("modules.migrations", "INFO") as logs:
            threads = [threading.Thread(target=start) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(execute("SELECT version FROM darsai_schema_version"), [(1,)])
        self.assertEqual(sum("migration 1 applied" in line for line in logs.output), 1)

    def test_a_failed_migration_leaves_nothing_behind(self):
        main.init_databases()

        def broken(cur):
            cur.execute("CREATE TABLE darsai_half_done (id INTEGER)")
            raise RuntimeError("migration failed")

        def fixed(cur):
            cur.execute("CREATE TABLE darsai_half_done (id INTEGER)")

        with patch.object(migrations, "MIGRATIONS", migrations.MIGRATIONS + [(2, "test", broken)]):
            with self.assertRaises(RuntimeError):
                migrations.migrate()
        self.assertEqual(migrations.schema_version(), 1)
        self.assertNotIn("darsai_half_done", self.tables())
        with patch.object(migrations, "MIGRATIONS", migrations.MIGRATIONS + [(2, "test", fixed)]), \
                patch.object(migrations, "LATEST_VERSION", 2):
            self.assertEqual(migrations.migrate(), 2)
        self.assertIn("darsai_half_done", self.tables())

    def test_a_newer_database_is_a_warning(self):
        main.init_databases()
        execute("INSERT INTO darsai_schema_version (version, name) VALUES (99, 'from a newer deploy')")
        with self.assertLogs("modules.migrations", "WARNING") as logs:
            self.assertEqual(migrations.migrate(), 99)
        self.assertIn("newer than this code knows (1)", logs.output[0])

    # ---------------------------------------------------------------- storage

    def test_practice_storage(self):
        main.init_databases()
        before, after = shared.record_answer(5, "high_school", "algebra", "easy", "first_try")
        self.assertEqual(before, 0.0)
        self.assertAlmostEqual(after, shared.next_mastery(0.0, "easy", "first_try"))
        shared.record_answer(5, "university", "calculus", "hard", "missed")
        self.assertEqual(list(shared.get_mastery(5)), [("university", "calculus"), ("high_school", "algebra")])
        self.assertEqual(execute("SELECT practice_answers FROM darsai_daily_activity WHERE user_id=5"), [(2,)])

        question = {"id": "q1", "topic": "algebra", "attempts": 0, "message_ids": [5]}
        shared.save_active_question(-100, 5, question)
        self.assertTrue(shared.update_active_question(-100, 5, dict(question, attempts=1)))
        self.assertEqual(shared.get_active_question(-100, 5)["attempts"], 1)
        self.assertIsNone(shared.get_active_question(5, 5), "per chat")
        self.assertFalse(shared.clear_active_question(-100, 5, "other"))
        self.assertTrue(shared.clear_active_question(-100, 5, "q1"))
        self.assertFalse(shared.update_active_question(-100, 5, question), "a finished question never comes back")

        shared.set_user_level(1, 5, "university")
        self.assertEqual(shared.get_user_level(999, 5), "university")

    def test_input_mode_storage(self):
        main.init_databases()
        input_mode.set_input_mode(1, 5, {"id": "m1", "mode": "solve", "message_ids": []})
        self.assertTrue(input_mode.change_input_mode(1, 5, "m1", {"last": {"id": "r1"}}, 10, max_message_ids=2))
        input_mode.change_input_mode(1, 5, "m1", None, 11, max_message_ids=2)
        input_mode.change_input_mode(1, 5, "m1", None, 12, max_message_ids=2)
        self.assertEqual(input_mode.get_input_mode(1, 5)["message_ids"], [11, 12])
        self.assertFalse(input_mode.change_input_mode(1, 5, "old", {"x": 1}))
        self.assertTrue(input_mode.claim_last_result(1, 5, "r1"))
        self.assertFalse(input_mode.claim_last_result(1, 5, "r1"), "only one tap gets it")
        input_mode.clear_input_mode(1, 5)
        self.assertIsNone(input_mode.get_input_mode(1, 5))

    def test_ai_usage_and_memory(self):
        main.init_databases()
        for _ in range(3):
            ai.reserve_ai_message(5)
        with self.assertRaises(ai.AILimitReached):
            ai.reserve_ai_message(5)
        day = ai.reserve_ai_message(6)
        ai.release_ai_message(6, day)
        ai.reserve_ai_message(6)
        with patch.object(ai, "FREE_DAILY_AI_LIMIT", 0):
            for _ in range(4):
                ai.reserve_ai_message(5)  # still counted with no limit, for /stats
        self.assertEqual(execute("SELECT user_id, count FROM darsai_ai_usage ORDER BY user_id"), [(5, 7), (6, 1)])

        ai.save_exchange(1, 5, "quadratics", "q1", "a1")
        ai.save_exchange(1, 5, "quadratics", "q2", "a2")
        ai.save_exchange(1, 5, "general", "hi", "hello")
        history = ai.load_history(1, 5, "quadratics", limit=3)
        self.assertEqual([m["content"] for m in history], ["a1", "q2", "a2"])
        self.assertEqual(ai.clear_history(1, 5, ["general"]), 2)
        self.assertEqual(ai.clear_history(1, 5, (), True), 4)

    def test_premium_waitlist_and_notify(self):
        main.init_databases()
        self.assertEqual(premium.set_choice(7, "photo", True, "menu", "en"), ["photo"])
        self.assertEqual(premium.set_choice(7, "photo", True, "menu", "en"), ["photo"])
        self.assertEqual(premium.set_choice(8, "msgs", True, "limit", "fa"), ["msgs"])
        self.assertEqual(premium.set_choice(8, "konkur", True, "menu", "fa"), ["konkur", "msgs"])
        self.assertEqual(premium.set_choice(9, "plan", True, "menu", "en"), ["plan"])
        self.assertEqual(premium.set_choice(9, "plan", False, "menu", "en"), [])
        self.assertEqual(premium.waitlist_summary(exclude=[]), {
            "students": 2, "sources": {"menu": 1, "limit": 1},
            "choices": {"konkur": 1, "msgs": 1, "photo": 1, "plan": 0, "ai": 0},
        })
        self.assertEqual(premium.waitlist_summary(exclude=[7])["students"], 1)

        notify.add_notice(10, "physics", "en")
        notify.add_notice(10, "physics", "fa")  # again: nothing changes
        notify.add_notice(10, "konkur", "en")
        notify.add_notice(11, "physics", "fa")
        notify.add_notice(99, "biology", "en")  # an admin
        # Picks for Astrology from before Biology replaced it: kept, but not counted.
        execute("INSERT INTO darsai_course_notify (user_id, course, language) VALUES (10, 'astrology', 'en'), (12, 'astrology', 'fa')")
        self.assertTrue(notify.wants_notice(10, "physics"))
        self.assertFalse(notify.wants_notice(11, "konkur"))
        self.assertEqual(execute("SELECT language FROM darsai_course_notify WHERE user_id=10 AND course='physics'"), [("en",)])
        self.assertEqual(notify.notice_summary(exclude=[99]), {
            "students": 2, "courses": {"physics": 2, "chemistry": 0, "biology": 0, "ai": 0, "astronomy": 0, "konkur": 1},
        })
        self.assertEqual(notify.notice_summary()["courses"]["biology"], 1)
        self.assertEqual(execute("SELECT COUNT(*) FROM darsai_course_notify WHERE course='astrology'"), [(2,)])

    def test_stats_numbers_leave_out_admins(self):
        main.init_databases()
        today = activity.utc_today()
        activity.mark_active(1)
        activity.mark_active(1)
        activity.mark_active(2, source="insta")
        activity.mark_active(3, today - timedelta(days=6))
        activity.mark_active(4, today - timedelta(days=7))
        activity.mark_active(100)  # an admin
        shared.record_answer(42, "high_school", "algebra", "easy", "first_try")
        shared.record_answer(100, "high_school", "algebra", "easy", "first_try")
        execute("INSERT INTO darsai_mastery (user_id, level, topic, correct_count, updated_at) VALUES "
                "(50, 'high_school', 'algebra', 4, NOW() - INTERVAL '3 days')")
        for _ in range(3):
            ai.reserve_ai_message(5)
        ai.reserve_ai_message(100)
        numbers = stats.collect_stats(today, admins=[100])
        # 1, 2, 42 (practised today: record_answer counts them active) and 5 (tutor) today; 3 and 50 this week.
        self.assertEqual(numbers["active"], {"today": 4, "week": 6, "total": 7})
        self.assertEqual(numbers["practice"], {"today": 1, "week": 1, "total": 5})
        self.assertEqual(numbers["tutor"], {"today": 3, "week": 3, "total": 3})
        self.assertEqual(numbers["limit_hits"], 1)
        new = numbers["new"]
        # mark_active writes darsai_first_seen with the time it runs, whatever day it is given.
        self.assertEqual((new["today"], new["week"], new["total"]), (4, 4, 4))
        self.assertEqual(new["sources"], [("insta", 1, 1, 1)])
        text = stats.format_stats(numbers)
        self.assertIn("insta: 1 · 1 · 1", text)
        self.assertIn("Admins (ADMIN_USER_IDS) are left out of every number.", text)

    # ---------------------------------------------------------------- screens with the database

    def test_setup_practice_and_notify_through_the_screens(self):
        main.init_databases()
        run(home.start_command, text_update("/start"))
        self.assertIn("which language", self.reply_text.call_args.args[0])
        for route in ("su:l:en", "su:v:middle_school", "su:c:math"):
            run(router.callback_router, button_update(f"d1:{STUDENT}:{route}"))
        self.assertEqual(student.get_student(STUDENT)["setup_done"], True)
        self.assertEqual(student.get_student(STUDENT)["level"], "middle_school")
        run(router.callback_router, button_update(f"d1:{STUDENT}:c:math:prac:n:linear_equations"))
        question = shared.get_active_question(STUDENT, STUDENT)
        run(typed.private_text, text_update(question["answer"]))
        self.assertTrue(self.reply_text.call_args.args[0].startswith("✅ Correct!"))
        self.assertIsNone(shared.get_active_question(STUDENT, STUDENT))
        run(router.callback_router, button_update(f"d1:{STUDENT}:c:physics:n"))
        self.assertTrue(notify.wants_notice(STUDENT, "physics"))
        # Set up with the current keyboard: no notice.
        setup._current.clear()
        run(setup.keyboard_notice, text_update("hello"))
        self.assertNotIn(t("en", "keyboard.notice"), [c.args[1] for c in self.send_message.call_args_list])


class NoDatabaseTests(unittest.TestCase):
    def test_migrations_need_a_database(self):
        with self.assertLogs("modules.migrations", "INFO") as logs:
            self.assertIsNone(migrations.migrate())
        self.assertIn("kept in memory", logs.output[0])
