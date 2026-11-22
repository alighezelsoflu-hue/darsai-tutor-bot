"""💎 Premium (the waitlist picks), the daily activity tracker and /stats."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import Update
from telegram.ext import TypeHandler

import config
import main
from modules import activity, ai, premium, stats, student
from modules.i18n import t
from modules.math.shared import record_answer
from modules.ui import home, router
from modules.ui import premium as premium_ui
from modules.ui import typed
from tests.test_ui import BOT, DATE, STUDENT, TelegramMocks, _chat, _user, button_update, run, text_update

CHOICE_ROUTES = [f"prem:a:{choice}:m" for choice in premium.CHOICES]


def routes(markup):
    return [b.callback_data.split(":", 2)[2] for row in markup.inline_keyboard for b in row]


def labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


class PremiumTests(TelegramMocks):
    def press(self, data, **kwargs):
        run(router.callback_router, button_update(data, **kwargs))

    def shown(self):
        call = self.edit_text.call_args
        return call.args[0], self.markup(call)

    def test_menu_has_premium_next_to_settings(self):
        run(home.start_command, text_update("/start"))
        menu = self.markup(self.reply_text.call_args)
        self.assertEqual(routes(menu)[-2:], ["set", "prem"])
        self.assertEqual(labels(menu)[-1], "💎 Premium")
        student.set_language(STUDENT, "fa")
        run(home.start_command, text_update("/start"))
        last_row = self.markup(self.reply_text.call_args).inline_keyboard[-1]
        # Mirrored for Persian: Settings on the right, Premium on the left.
        self.assertEqual([b.text for b in last_row], ["💎 پریمیوم", "⚙️ تنظیمات"])

    def test_premium_screen_says_it_is_not_ready_and_asks(self):
        self.press(f"d1:{STUDENT}:prem")
        text, markup = self.shown()
        for expected in (
            "💎 DarsAI Premium", "Premium isn't ready yet", "checks each step you send",
            "everything in the menu is free (the tutor has a daily limit of 3 messages)",
            "What would you want most from Premium?",
        ):
            self.assertIn(expected, text)
        self.assertNotIn("Thanks", text)
        self.assertEqual(routes(markup), CHOICE_ROUTES + ["home"])
        self.assertEqual(labels(markup)[0], "🎯 Konkur exam prep")

    def test_picks_are_saved_thanked_and_can_be_removed(self):
        self.press(f"d1:{STUDENT}:prem:a:photo:m")
        self.assertEqual(premium.get_choices(STUDENT), ["photo"])
        self.assertIn("Thanks", self.answer.call_args.args[0])
        text, markup = self.shown()
        self.assertIn("Your picks are saved", text)
        self.assertIn("📷 Photo solving ✓", labels(markup))
        self.assertIn("prem:r:photo:m", routes(markup))
        self.assertEqual(premium._FALLBACK[(STUDENT, "photo")]["source"], "menu")
        self.assertEqual(premium._FALLBACK[(STUDENT, "photo")]["language"], "en")

        self.press(f"d1:{STUDENT}:prem:a:konkur:m")
        self.assertEqual(premium.get_choices(STUDENT), ["konkur", "photo"])
        self.press(f"d1:{STUDENT}:prem:r:photo:m")
        self.assertEqual(premium.get_choices(STUDENT), ["konkur"])
        self.assertEqual(self.answer.call_args.args[0], "Removed")
        # A button from an older message does what its label said, so it can't undo a newer pick.
        self.press(f"d1:{STUDENT}:prem:a:konkur:m")
        self.assertEqual(premium.get_choices(STUDENT), ["konkur"])

        self.press(f"d1:{STUDENT}:prem:r:konkur:m")
        text, _ = self.shown()
        self.assertNotIn("Thanks", text, "no picks left: off the waitlist")

    def test_reopening_shows_the_picks(self):
        premium.set_choice(STUDENT, "plan", True, "menu", "en")
        self.press(f"d1:{STUDENT}:prem")
        text, markup = self.shown()
        self.assertIn("Your picks are saved", text)
        self.assertIn("📊 Study plan and weekly report ✓", labels(markup))

    def test_persian_premium_screen(self):
        student.set_language(STUDENT, "fa")
        self.press(f"d1:{STUDENT}:prem")
        text, markup = self.shown()
        self.assertIn("اشتراک ویژه‌ی DarsAI", text)
        self.assertIn("محدودیت روزانه‌ی ۳ پیام", text)
        self.assertEqual(labels(markup), [t("fa", f"premium.choice.{c}") for c in premium.CHOICES] + ["🏠 منو"])
        self.press(f"d1:{STUDENT}:prem:a:konkur:m")
        self.assertEqual(premium._FALLBACK[(STUDENT, "konkur")]["language"], "fa")
        self.assertIn("مرسی", self.shown()[0])

    def test_no_limit_means_no_limit_in_the_text(self):
        with patch.object(premium_ui, "FREE_DAILY_AI_LIMIT", 0):
            self.press(f"d1:{STUDENT}:prem")
        text, _ = self.shown()
        self.assertIn("everything in the menu is free.", text)
        self.assertNotIn("daily limit", text)

    def test_unknown_picks_expire(self):
        self.press(f"d1:{STUDENT}:prem:a:wizard:m")
        self.assertIn("expired", self.answer.call_args.args[0])
        self.press(f"d1:{STUDENT}:prem:a:photo:x")
        self.assertIn("expired", self.answer.call_args.args[0])
        self.assertEqual(premium.get_choices(STUDENT), [])
        self.edit_text.assert_not_called()

    def test_groups_name_the_owner(self):
        self.press(f"d1:{STUDENT}:prem", chat_type="supergroup")
        self.assertTrue(self.shown()[0].startswith("👤 Sara\n💎 DarsAI Premium"))
        self.press(f"d1:{STUDENT}:prem:a:photo:m", user_id=7, chat_type="supergroup")
        self.assertEqual(premium.get_choices(7), [], "someone else's buttons")

    def test_subscribe_opens_the_premium_screen(self):
        run(premium_ui.subscribe_command, text_update("/subscribe", language_code="fa"))
        call = self.reply_text.call_args
        self.assertIn("اشتراک ویژه هنوز آماده نیست", call.args[0])
        self.assertEqual(routes(self.markup(call)), CHOICE_ROUTES + ["home"])


class LimitOfferTests(TelegramMocks):
    def setUp(self):
        super().setUp()
        patcher = patch.object(ai, "call_ai_provider", AsyncMock(return_value="An answer."))
        patcher.start()
        self.addCleanup(patcher.stop)

    def use_up_the_tutor(self):
        run(router.callback_router, button_update(f"d1:{STUDENT}:tutor"))
        for _ in range(3):  # FREE_DAILY_AI_LIMIT=3 in tests
            run(typed.private_text, text_update("question"))
        run(typed.private_text, text_update("one more"))
        call = self.reply_text.call_args
        return call.args[0], self.markup(call)

    def test_limit_message_offers_the_picks(self):
        text, markup = self.use_up_the_tutor()
        self.assertIn("You've used all 3 tutor messages", text)
        self.assertIn("Premium is coming", text)
        self.assertEqual(routes(markup), [f"prem:a:{c}:l" for c in premium.CHOICES] + ["home"])

        run(router.callback_router, button_update(f"d1:{STUDENT}:prem:a:msgs:l"))
        self.assertEqual(premium._FALLBACK[(STUDENT, "msgs")]["source"], "limit")
        edited = self.edit_text.call_args
        self.assertIn("You've used all 3 tutor messages", edited.args[0], "the limit text stays")
        self.assertIn("Your picks are saved", edited.args[0])
        self.assertIn("prem:r:msgs:l", routes(self.markup(edited)))

        # Already on the waitlist: the next limit message doesn't ask again.
        run(typed.private_text, text_update("and another"))
        call = self.reply_text.call_args
        self.assertIn("You've used all 3 tutor messages", call.args[0])
        self.assertNotIn("Premium", call.args[0])
        self.assertEqual(routes(self.markup(call)), ["home"])

    def test_persian_limit_offer(self):
        student.set_language(STUDENT, "fa")
        text, markup = self.use_up_the_tutor()
        self.assertIn("همه‌ی ۳ پیامی", text)
        self.assertIn("اشتراک ویژه به‌زودی میاد", text)
        self.assertEqual(labels(markup)[0], "🎯 آمادگی کنکور")


class ActivityTests(TelegramMocks):
    def today_row(self, user_id=STUDENT):
        return activity._FALLBACK.get((activity.utc_today(), user_id))

    def track(self, update):
        run(stats.track_activity, update)

    def test_the_tracker_runs_before_everything_else(self):
        handlers = main.telegram_app.handlers[min(main.telegram_app.handlers)]
        self.assertTrue(any(isinstance(h, TypeHandler) and h.callback is stats.track_activity for h in handlers))
        self.assertLess(min(main.telegram_app.handlers), -1, "before the anonymous-sender check, which stops updates")

    def test_updates_go_through_the_tracker_and_on_to_the_screens(self):
        with patch.object(main.telegram_app, "_initialized", True):
            asyncio.run(main.telegram_app.process_update(button_update(f"d1:{STUDENT}:prem")))
        self.assertIsNotNone(self.today_row())
        self.assertIn("Premium isn't ready yet", self.edit_text.call_args.args[0])

    def test_students_are_noted_once_a_day(self):
        with patch.object(activity, "mark_active", wraps=activity.mark_active) as mark:
            self.track(button_update(f"d1:{STUDENT}:home"))
            self.track(text_update("hello"))
            self.track(text_update("/start"))
        self.assertEqual(mark.call_count, 1)
        self.assertEqual(self.today_row(), {"practice_answers": 0})

    def test_what_counts(self):
        group_reply = text_update("x = 3", chat_type="supergroup", user_id=11, reply_to=5)
        group_command = text_update("/start", chat_type="supergroup", user_id=12)
        group_chatter = text_update("hi all", chat_type="supergroup", user_id=13)
        anonymous = Update.de_json({"update_id": 4, "message": {
            "message_id": 3, "date": DATE, "chat": _chat("supergroup", 14), "text": "/start",
            "from": {"id": 1087968824, "is_bot": True, "first_name": "Group"},
            "sender_chat": {"id": -1001, "type": "supergroup", "title": "Class"},
        }}, BOT)
        blocked = Update.de_json({"update_id": 5, "my_chat_member": {
            "chat": _chat("private", 15), "from": _user(15, "en"), "date": DATE,
            "old_chat_member": {"user": {"id": 1, "is_bot": True, "first_name": "DarsAI"}, "status": "member"},
            "new_chat_member": {"user": {"id": 1, "is_bot": True, "first_name": "DarsAI"}, "status": "kicked", "until_date": 0},
        }}, BOT)
        for update in (group_reply, group_command, group_chatter, anonymous, blocked):
            self.track(update)
        seen = {uid for (_, uid) in activity._FALLBACK}
        self.assertEqual(seen, {11, 12})

    def test_start_links_give_new_students_a_source(self):
        self.track(text_update("/start insta_story-2", user_id=21))
        self.assertEqual(activity._FIRST_SEEN[21]["source"], "insta_story-2")
        stats._seen.clear()  # the next day
        self.track(text_update("/start telegram_ad", user_id=21))
        self.assertEqual(activity._FIRST_SEEN[21]["source"], "insta_story-2", "only the first source is kept")

        self.track(text_update("hello", user_id=22))
        stats._seen.clear()
        self.track(text_update("/start telegram_ad", user_id=22))
        self.assertIsNone(activity._FIRST_SEEN[22]["source"], "not new any more: no source")

    def test_invalid_start_payloads_are_ignored(self):
        payloads = ["/start bad!link", "/start " + "a" * 65, "/start two words", "/start", "/starter x", "/help src"]
        for user_id, text in enumerate(payloads, start=30):
            self.track(text_update(text, user_id=user_id))
            self.assertIsNone(activity._FIRST_SEEN[user_id]["source"], text)
        self.track(text_update("/start@DarsAIBot src_1", user_id=40))
        self.assertEqual(activity._FIRST_SEEN[40]["source"], "src_1")
        self.track(text_update("/start src_1", user_id=41, chat_type="supergroup"))
        self.assertIsNone(activity._FIRST_SEEN[41]["source"], "start links open a private chat")

    def test_a_failure_is_only_logged_and_tried_again(self):
        with patch.object(activity, "mark_active", side_effect=RuntimeError("database is down")):
            with self.assertLogs("modules.stats", "WARNING"):
                self.track(text_update("hello"))
        self.track(text_update("hello"))
        self.assertIsNotNone(self.today_row())

    def test_practice_answers_are_counted_per_day(self):
        record_answer(STUDENT, "high_school", "algebra", "easy", "first_try")
        record_answer(STUDENT, "high_school", "algebra", "easy", "missed")
        self.assertEqual(self.today_row(), {"practice_answers": 2})


class StatsTests(TelegramMocks):
    ADMIN = 99

    def setUp(self):
        super().setUp()
        patcher = patch.object(stats, "ADMIN_USER_IDS", frozenset({self.ADMIN}))
        patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, user_id=ADMIN, chat_type="private"):
        self.reply_text.reset_mock()
        run(stats.stats_command, text_update("/stats", user_id=user_id, chat_type=chat_type))
        return self.reply_text.call_args.args[0] if self.reply_text.called else None

    def test_admin_ids_from_the_environment(self):
        self.assertEqual(config.parse_admin_ids("123, 456 789"), (frozenset({123, 456, 789}), ()))
        self.assertEqual(config.parse_admin_ids(""), (frozenset(), ()))
        self.assertEqual(config.parse_admin_ids('"123"'), (frozenset({123}), ()), "quotes are removed")
        self.assertEqual(config.parse_admin_ids("'123', \"456\""), (frozenset({123, 456}), ()))
        self.assertEqual(config.parse_admin_ids("123, @ali, 12x, ²"), (frozenset({123}), ("@ali", "12x", "²")))

    def test_a_typo_is_only_a_warning(self):
        with patch.object(stats, "ADMIN_USER_IDS_IGNORED", ("@ali",)), self.assertLogs("modules.stats", "INFO") as logs:
            stats.log_admin_setting()
        self.assertIn("WARNING:modules.stats:ADMIN_USER_IDS: ignored '@ali'", logs.output[0])
        self.assertIn("1 admin user id(s)", logs.output[1])

    def test_others_get_no_reply_and_the_log_shows_their_id(self):
        with self.assertLogs("modules.stats", "INFO") as logs:
            self.assertIsNone(self.ask(user_id=STUDENT))
        self.assertIn(f"user id {STUDENT}", logs.output[0])
        with self.assertLogs("modules.stats", "INFO"):
            self.assertIsNone(self.ask(chat_type="supergroup"), "admins only in a private chat")

    def test_the_numbers(self):
        today = activity.utc_today()
        activity.mark_active(1)
        activity.mark_active(2)
        activity.mark_active(3, today - timedelta(days=6))
        activity.mark_active(4, today - timedelta(days=7))  # outside the last 7 days
        record_answer(STUDENT, "high_school", "algebra", "easy", "first_try")
        record_answer(STUDENT, "high_school", "algebra", "easy", "missed")
        for _ in range(3):
            ai.reserve_ai_message(5)  # hits the limit of 3
        ai.reserve_ai_message(6)
        premium.set_choice(7, "photo", True, "menu", "en")
        premium.set_choice(8, "msgs", True, "limit", "fa")
        premium.set_choice(8, "photo", True, "menu", "fa")
        student.set_language(9, "fa")

        text = self.ask()
        self.assertIn(f"📊 DarsAI stats · {today.isoformat()} (UTC)", text)
        lines = text.splitlines()

        def after(title):
            return lines[lines.index(title) + 1]

        # Today: 1, 2, the student (practice), 5 and 6 (tutor). The week adds 3. All time adds 4, 7, 8 and 9.
        self.assertEqual(after("👥 Active students"), "Today: 5 · Last 7 days: 6 · All time: 10")
        self.assertEqual(after("✍️ Practice answers"), "Today: 2 · Last 7 days: 2 · All time: 2")
        self.assertEqual(after("🧑‍🏫 Tutor messages"), "Today: 4 · Last 7 days: 4 · All time: 4")
        self.assertIn("⏳ Hit the daily limit today: 1 student (limit 3)", lines)
        self.assertIn("💎 Premium waitlist: 2 students", lines)
        self.assertIn("From 💎 Premium: 1 · From the limit message: 1", lines, "student 8 first picked on the limit message")
        premium.set_choice(7, "ai", True, "menu", "en")
        lines = self.ask().splitlines()
        # Only the tracker (mark_active) records first sightings: students 1 to 4, all today.
        self.assertEqual(after("🔗 New students"), "Today: 4 · Last 7 days: 4 · All time: 4")
        for line in ("🎯 Konkur exam prep: 0", "🧑‍🏫 More tutor messages: 1", "📷 Photo solving: 2",
                     "📊 Study plan and weekly report: 0", "🤖 AI course: 1"):
            self.assertIn(line, lines)
        self.assertNotIn("Counting by day started", text, "the daily table covers the whole week")

    def test_new_students_by_start_link(self):
        now = datetime.now(timezone.utc)
        seen = {
            1: ("insta", now), 2: ("insta", now - timedelta(days=3)), 3: ("insta", now - timedelta(days=30)),
            4: ("ad_nov", now), 5: (None, now), 6: (None, now - timedelta(days=100)),
        }
        for user_id, (source, at) in seen.items():
            activity._FIRST_SEEN[user_id] = {"source": source, "at": at}
        lines = self.ask().splitlines()
        start = lines.index("🔗 New students")
        self.assertEqual(lines[start + 1:start + 6], [
            "Today: 3 · Last 7 days: 4 · All time: 6",
            "By start link (today · last 7 days · all time):",
            "insta: 1 · 2 · 3",
            "ad_nov: 1 · 1 · 1",
            "No link: 1 · 1 · 2",
        ])

    def test_many_links_are_added_up(self):
        now = datetime.now(timezone.utc)
        for user_id in range(stats.MAX_SOURCES + 3):
            activity._FIRST_SEEN[user_id] = {"source": f"link{user_id:02d}", "at": now}
        text = self.ask()
        self.assertIn("link14: 1 · 1 · 1", text)
        self.assertNotIn("link15", text)
        self.assertIn("3 more links: 3 · 3 · 3", text)

    def test_admins_are_left_out_of_every_number(self):
        admin = self.ADMIN
        activity.mark_active(admin, source="insta")
        record_answer(admin, "high_school", "algebra", "easy", "first_try")
        for _ in range(3):
            ai.reserve_ai_message(admin)
        ai.save_exchange(admin, admin, "math", "q", "a")
        premium.set_choice(admin, "photo", True, "menu", "en")
        student.set_language(admin, "fa")
        text = self.ask()
        for line in (
            "Today: 0 · Last 7 days: 0 · All time: 0",
            "⏳ Hit the daily limit today: 0 students (limit 3)",
            "💎 Premium waitlist: 0 students",
            "📷 Photo solving: 0",
            "Admins (ADMIN_USER_IDS) are left out of every number.",
        ):
            self.assertIn(line, text)
        self.assertNotIn("insta", text)
        self.assertNotIn(": 1", text)

    def test_a_new_table_says_when_counting_started(self):
        activity.mark_active(1)
        text = self.ask()
        self.assertIn(f"Counting by day started {activity.utc_today().isoformat()}", text)

    def test_no_limit(self):
        with patch.object(stats, "FREE_DAILY_AI_LIMIT", 0):
            self.assertIn("There is no daily tutor limit", self.ask())

    def test_stats_is_not_in_the_command_menu_or_help(self):
        self.assertNotIn("/stats", main.help_text())
