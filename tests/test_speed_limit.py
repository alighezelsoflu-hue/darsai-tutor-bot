"""Phase 1 step 9: the per-student speed limit (modules/ratelimit.py), in the chat (ui/limit.py) and on the Mini
App's /api routes (webapp.api_student)."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from telegram import Update
from telegram.ext import TypeHandler

import config
import main
from modules import activity, ratelimit, stats, webapp
from modules.i18n import t
from modules.ui import groups, limit
from modules.ui import privacy as privacy_ui
from tests.test_miniapp import init_data
from tests.test_ui import BOT, BOT_USER, DATE, STUDENT, TelegramMocks, button_update, text_update

ANONYMOUS_BOT = {"id": 1087968824, "is_bot": True, "first_name": "Group", "username": "GroupAnonymousBot"}
GROUP = {"id": -1001, "type": "supergroup", "title": "Class 10B"}


class Clock:
    """A clock the test moves by hand."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class SpeedLimitTests(TelegramMocks):
    def setUp(self):
        super().setUp()
        self.clock = Clock()
        self.budget = ratelimit.SpeedLimit("RATE_LIMIT_ACTIONS", clock=self.clock)
        patcher = patch.multiple(config, RATE_LIMIT_ACTIONS=3, RATE_LIMIT_WINDOW_SECONDS=10)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_limit_and_the_window(self):
        self.assertEqual([self.budget.allow(STUDENT) for _ in range(4)], [True, True, True, False])
        self.assertTrue(self.budget.allow(7), "other students have their own budget")
        self.clock.now += 9.9
        self.assertFalse(self.budget.allow(STUDENT))
        self.clock.now += 0.1  # the first three are 10 s old now
        self.assertTrue(self.budget.allow(STUDENT))

    def test_a_sliding_window_not_fixed_blocks(self):
        self.budget.allow(STUDENT)
        self.clock.now += 6
        self.budget.allow(STUDENT)
        self.budget.allow(STUDENT)
        self.clock.now += 4  # only the first is 10 s old
        self.assertTrue(self.budget.allow(STUDENT))
        self.assertFalse(self.budget.allow(STUDENT))

    def test_refused_actions_do_not_count(self):
        for _ in range(3):
            self.budget.allow(STUDENT)
        for _ in range(50):
            self.clock.now += 0.1
            self.assertFalse(self.budget.allow(STUDENT))
        self.clock.now = 1010.0  # 10 s after the three allowed ones, however much was refused since
        self.assertTrue(self.budget.allow(STUDENT))
        self.assertEqual(self.budget.refused, 50)

    def test_retry_after(self):
        self.assertEqual(self.budget.retry_after(STUDENT), 0)
        for _ in range(3):
            self.budget.allow(STUDENT)
            self.clock.now += 1
        self.assertAlmostEqual(self.budget.retry_after(STUDENT), 7)

    def test_one_warning_per_window(self):
        self.assertTrue(self.budget.first_refusal(STUDENT))
        self.assertFalse(self.budget.first_refusal(STUDENT))
        self.assertTrue(self.budget.first_refusal(7))
        self.clock.now += 10
        self.assertTrue(self.budget.first_refusal(STUDENT))

    def test_admins_have_no_limit(self):
        with patch.object(config, "ADMIN_USER_IDS", frozenset({STUDENT})):
            self.assertTrue(all(self.budget.allow(STUDENT) for _ in range(100)))
        self.assertEqual(self.budget.students(), 0, "nothing is kept for admins")

    def test_idle_students_are_dropped_from_memory(self):
        for user_id in range(100):
            self.budget.allow(user_id)
        self.assertEqual(self.budget.students(), 100)
        self.clock.now += ratelimit.SWEEP_SECONDS
        self.budget.allow(STUDENT)
        self.assertEqual(self.budget.students(), 1)

    def test_forget(self):
        for _ in range(3):
            self.budget.allow(STUDENT)
        self.budget.first_refusal(STUDENT)
        self.budget.forget(STUDENT)
        self.assertTrue(self.budget.allow(STUDENT))
        self.assertTrue(self.budget.first_refusal(STUDENT))

    def test_a_note_lasts_while_the_student_is_refused(self):
        for _ in range(3):
            self.budget.allow(STUDENT)
        self.assertIsNone(self.budget.note(STUDENT))
        self.budget.set_note(STUDENT, "fa")
        self.clock.now += 5
        self.assertFalse(self.budget.allow(STUDENT))
        self.assertEqual(self.budget.note(STUDENT), "fa")
        self.clock.now += 5  # the window is over, and so is the note
        self.assertIsNone(self.budget.note(STUDENT))
        self.budget.set_note(STUDENT, "fa")
        self.assertTrue(self.budget.allow(STUDENT))
        self.assertIsNone(self.budget.note(STUDENT), "an allowed action (e.g. a language switch) drops it")
        self.budget.set_note(STUDENT, "fa")
        self.budget.forget(STUDENT)
        self.assertIsNone(self.budget.note(STUDENT))

    def test_threads_never_let_more_through(self):
        """run_local.py serves the Mini App from another thread."""
        allowed = []

        def act():
            for _ in range(200):
                allowed.append(self.budget.allow(STUDENT))

        workers = [threading.Thread(target=act) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(allowed.count(True), 3)

    def test_the_settings(self):
        self.assertEqual(ratelimit.ACTIONS.setting, "RATE_LIMIT_ACTIONS")
        self.assertEqual(ratelimit.READS.setting, "RATE_LIMIT_API_READS")
        self.assertEqual(ratelimit.ACTIONS.limit, 3)


class LimitedTestCase(TelegramMocks):
    """At most 3 actions in 10 s, on a clock the test moves."""

    LIMIT = 3

    def setUp(self):
        super().setUp()
        self.existing_student()
        self.clock = Clock()
        patchers = [patch.multiple(config, RATE_LIMIT_ACTIONS=self.LIMIT, RATE_LIMIT_API_READS=self.LIMIT,
                                   RATE_LIMIT_WINDOW_SECONDS=10)]
        patchers += [patch.object(budget, "clock", self.clock) for budget in ratelimit.BUDGETS]
        patchers.append(patch.object(main.telegram_app, "_initialized", True))
        # Command handlers compare the bot's username, which only Telegram can tell an uninitialised bot.
        patchers.append(patch.object(type(BOT), "username", PropertyMock(return_value="darsai_test_bot")))
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def process(self, update: Update) -> None:
        with self.assertNoLogs(level="ERROR"):  # main.error_handler logs every failed update
            asyncio.run(main.telegram_app.process_update(update))

    def press(self, data=f"d1:{STUDENT}:set", **kwargs) -> None:
        self.process(button_update(data, **kwargs))

    def pop_ups(self):
        return [call.args[0] if call.args else None for call in self.answer.call_args_list]


class ChatTests(LimitedTestCase):
    def test_handlers_run_in_order_tracker_limit_anonymous_check(self):
        app = main.telegram_app
        self.assertEqual(sorted(app.handlers)[:3], [-3, -2, -1])
        self.assertIs(app.handlers[-3][0].callback, stats.track_activity)
        (handler,) = app.handlers[-2]
        self.assertIsInstance(handler, TypeHandler)
        self.assertIs(handler.callback, limit.speed_limit)
        self.assertIs(app.handlers[-1][0].callback, groups.anonymous_sender)

    def test_button_presses_over_the_limit_get_a_pop_up_every_time(self):
        for _ in range(self.LIMIT):
            self.press()
        self.assertEqual(self.edit_text.call_count, self.LIMIT)
        self.press()
        self.press()
        self.assertEqual(self.edit_text.call_count, self.LIMIT, "the screens are skipped")
        self.assertEqual(self.pop_ups()[-2:], [t("en", "rate.button")] * 2)
        self.reply_text.assert_not_called()
        self.send_message.assert_not_called()

    def test_refused_taps_read_the_language_once(self):
        for _ in range(self.LIMIT):
            self.press()
        with patch.object(limit, "student_language", wraps=limit.student_language) as read:
            for _ in range(10):
                self.press()
        self.assertEqual(read.call_count, 1)
        self.assertEqual(self.pop_ups()[-10:], [t("en", "rate.button")] * 10)

    def test_the_pop_up_is_in_the_students_language(self):
        self.press(f"d1:{STUDENT}:set:lang:fa")
        for _ in range(self.LIMIT):
            self.press()
        self.assertEqual(self.pop_ups()[-1], "⏳ یه کم آروم‌تر! چند ثانیه دیگه دوباره امتحان کن.")

    def test_messages_over_the_limit_get_one_warning_then_nothing(self):
        for _ in range(self.LIMIT):
            self.process(text_update("hello"))
        handled = self.reply_text.call_count
        self.assertEqual(handled, self.LIMIT)
        for _ in range(5):
            self.process(text_update("/start"))
        self.assertEqual(self.reply_text.call_count, handled + 1)
        self.assertEqual(self.reply_text.call_args.args[0], t("en", "rate.message"))
        self.send_message.assert_not_called()

    def test_after_the_window_everything_works_again_with_a_new_warning(self):
        for _ in range(self.LIMIT + 2):
            self.process(text_update("hello"))
        self.clock.now += 10
        self.process(text_update("hello"))
        self.assertNotEqual(self.reply_text.call_args.args[0], t("en", "rate.message"), "handled again")
        for _ in range(self.LIMIT):
            self.process(text_update("hello"))
        self.assertEqual(self.reply_text.call_args.args[0], t("en", "rate.message"), "a new window, a new warning")

    def test_a_slowed_down_student_still_counts_as_active(self):
        for _ in range(self.LIMIT + 1):
            self.press()
        stats._seen.clear()
        activity._FALLBACK.clear()
        self.press()  # refused
        self.assertEqual(self.pop_ups()[-1], t("en", "rate.button"))
        self.assertIn((activity.utc_today(), STUDENT), activity._FALLBACK)

    def test_admins_have_no_limit(self):
        with patch.object(config, "ADMIN_USER_IDS", frozenset({STUDENT})):
            for _ in range(self.LIMIT * 3):
                self.press()
        self.assertEqual(self.edit_text.call_count, self.LIMIT * 3)
        self.assertNotIn(t("en", "rate.button"), self.pop_ups())

    def test_edited_messages_and_the_bot_joining_a_group_do_not_count(self):
        for _ in range(self.LIMIT):
            self.press()
        edited = Update.de_json({"update_id": 3, "edited_message": {
            "message_id": 1, "date": DATE, "edit_date": DATE, "chat": {"id": STUDENT, "type": "private"},
            "from": {"id": STUDENT, "is_bot": False, "first_name": "Sara"}, "text": "hello"}}, BOT)
        self.process(edited)
        self.assertEqual(ratelimit.ACTIONS.refused, 0)
        joined = Update.de_json({"update_id": 4, "my_chat_member": {
            "chat": GROUP, "from": {"id": STUDENT, "is_bot": False, "first_name": "Sara"}, "date": DATE,
            "old_chat_member": {"user": BOT_USER, "status": "left"},
            "new_chat_member": {"user": BOT_USER, "status": "member"}}}, BOT)
        self.process(joined)
        self.assertIn("Everyone can send /start", self.send_message.call_args.args[1], "the greeting still goes out")
        self.assertEqual(ratelimit.ACTIONS.refused, 0)


class GroupTests(LimitedTestCase):
    def test_commands_and_replies_in_groups_count(self):
        for _ in range(self.LIMIT):
            self.process(text_update("/start", chat_type="supergroup"))
        self.process(text_update("1", chat_type="supergroup", reply_to=99))
        self.assertEqual(self.reply_text.call_args.args[0], t("en", "rate.message"))
        self.assertEqual(ratelimit.ACTIONS.refused, 1)

    def test_other_group_messages_do_not_count(self):
        for _ in range(self.LIMIT * 2):
            self.process(text_update("just chatting", chat_type="supergroup"))
        self.assertEqual(ratelimit.ACTIONS.students(), 0)

    def test_anonymous_posts_do_not_count_and_still_get_their_answer(self):
        anonymous = {"message_id": 1, "date": DATE, "chat": GROUP, "from": ANONYMOUS_BOT, "sender_chat": GROUP,
                      "text": "/start", "entities": [{"type": "bot_command", "offset": 0, "length": 6}]}
        for _ in range(self.LIMIT * 2):
            self.process(Update.de_json({"update_id": 5, "message": anonymous}, BOT))
        self.assertEqual(self.reply_text.call_count, self.LIMIT * 2)
        self.assertIn("anonymously", self.reply_text.call_args.args[0])
        self.assertEqual(ratelimit.ACTIONS.students(), 0)

    def test_each_student_in_a_group_has_their_own_budget(self):
        for _ in range(self.LIMIT + 1):
            self.process(text_update("/start", chat_type="supergroup"))
        self.process(text_update("/start", chat_type="supergroup", user_id=7))
        self.assertNotEqual(self.reply_text.call_args.args[0], t("en", "rate.message"))


class DeleteMyDataTests(LimitedTestCase):
    def test_the_counts_are_forgotten(self):
        for _ in range(self.LIMIT + 1):
            self.press()
        for _ in range(2):
            ratelimit.READS.allow(STUDENT)
        privacy_ui.forget_in_process(SimpleNamespace(), STUDENT)
        self.assertEqual(ratelimit.ACTIONS.students(), 0)
        self.assertEqual(ratelimit.READS.students(), 0)
        self.press()
        self.assertNotEqual(self.pop_ups()[-1], t("en", "rate.button"))


probe = FastAPI()


@probe.post("/api/probe")
async def probe_write(student=Depends(webapp.api_student("write"))):
    """A change, like the ones Mini App step 2 adds."""
    return {"user_id": student["user_id"]}


class ApiTests(LimitedTestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(main.api)  # no startup: the routes only
        self.headers = {"Authorization": f"tma {init_data()}"}

    def progress(self):
        return self.client.get("/api/me/progress", headers=self.headers)

    def test_reads_over_their_limit_get_429_with_retry_after(self):
        for _ in range(self.LIMIT):
            self.assertEqual(self.progress().status_code, 200)
        refused = self.progress()
        self.assertEqual(refused.status_code, 429)
        self.assertEqual(refused.headers["retry-after"], "10")
        ping = self.client.post("/api/miniapp/ping", headers=self.headers, json={"total_ms": 1})
        self.assertEqual(ping.status_code, 429, "the ping uses the reads' budget")
        self.clock.now += 10
        self.assertEqual(self.progress().status_code, 200)

    def test_launch_data_is_checked_first(self):
        for _ in range(self.LIMIT + 1):
            self.progress()
        self.assertEqual(self.client.get("/api/me/progress").status_code, 401)

    def test_page_loads_do_not_block_the_chat(self):
        for _ in range(self.LIMIT + 1):
            self.progress()
        self.press()
        self.assertEqual(self.edit_text.call_count, 1, "chat buttons still work")

    def test_the_chat_does_not_block_page_loads(self):
        for _ in range(self.LIMIT + 1):
            self.press()
        self.assertEqual(self.pop_ups()[-1], t("en", "rate.button"))
        self.assertEqual(self.progress().status_code, 200)

    def test_writes_share_the_chats_budget(self):
        writes = TestClient(probe)
        for _ in range(self.LIMIT - 1):
            self.press()
        self.assertEqual(writes.post("/api/probe", headers=self.headers).json(), {"user_id": STUDENT})
        self.assertEqual(writes.post("/api/probe", headers=self.headers).status_code, 429)
        self.press()
        self.assertEqual(self.pop_ups()[-1], t("en", "rate.button"))

    def test_admins_have_no_limit(self):
        with patch.object(config, "ADMIN_USER_IDS", frozenset({STUDENT})):
            self.assertTrue(all(self.progress().status_code == 200 for _ in range(self.LIMIT * 2)))

    def test_the_page_shows_the_slow_text(self):
        script = self.client.get("/app/app.js").text
        self.assertIn("response.status === 429", script)
        self.assertIn('"app.slow"', script)
        self.assertIn("⏳", t("fa", "app.slow"))

    def test_an_unknown_kind_is_a_mistake(self):
        with self.assertRaises(KeyError):
            webapp.api_student("delete")
