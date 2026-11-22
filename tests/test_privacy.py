"""🔒 Privacy: the policy, and 🗑 Delete my data (in-memory storage; tests/test_postgres.py has the SQL)."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import config
from modules import activity, ai, input_mode, notify, premium, privacy, stats, student
from modules.i18n import t
from modules.math import shared
from modules.ui import home, router, setup, typed
from modules.ui import privacy as privacy_ui
from telegram import Update

from tests.test_ui import BOT, BOT_USER, DATE, STUDENT, TelegramMocks, _user, button_update, run, text_update

OTHER = 77


class PolicyTests(TelegramMocks):
    def press(self, data, **kwargs):
        run(router.callback_router, button_update(data, **kwargs))

    def shown(self):
        call = self.edit_text.call_args
        return call.args[0], self.markup(call)

    def labels(self, markup):
        return [[b.text for b in row] for row in markup.inline_keyboard]

    def test_settings_has_privacy(self):
        self.press(f"d1:{STUDENT}:set")
        self.assertIn(["🔒 Privacy"], self.labels(self.shown()[1]))
        self.press(f"d1:{STUDENT}:priv")
        text, markup = self.shown()
        self.assertTrue(text.startswith("🔒 Privacy · DarsAI\n\nWhat the bot saves about you, and why:"))
        self.assertEqual(self.labels(markup), [["🗑 Delete my data"], ["🔙 Settings"]])

    def test_the_policy_names_who_receives_data(self):
        for lang in ("en", "fa"):
            screen = SimpleNamespace(lang=lang, private=True, t=lambda key, **params: t(lang, key, **params))
            text = privacy_ui.policy_text(screen)
            with self.subTest(lang=lang):
                self.assertIn("Groq", text)
                self.assertIn("Render", text)
                self.assertIn("Neon", text)
                self.assertNotIn("Sentry", text, "only when SENTRY_DSN is set")
                self.assertTrue(text.endswith(t(lang, "privacy.delete")), "no contact line while PRIVACY_CONTACT is empty")
                self.assertLess(len(text), 4096, "one Telegram message")
        with patch.multiple(config, SENTRY_DSN="https://key@o1.ingest.sentry.io/2", PRIVACY_CONTACT="@darsai_support",
                            AI_PROVIDER="openrouter"):
            screen = SimpleNamespace(lang="en", private=True, t=lambda key, **params: t("en", key, **params))
            text = privacy_ui.policy_text(screen)
        self.assertIn("go to OpenRouter (USA)", text)
        self.assertIn("• Error reports go to Sentry, without what you send.", text)
        self.assertTrue(text.endswith("Questions about your data: @darsai_support"))

    def test_privacy_and_deletemydata_commands(self):
        run(privacy_ui.privacy_command, text_update("/privacy", language_code="fa"))
        call = self.reply_text.call_args
        self.assertTrue(call.args[0].startswith("🔒 حریم خصوصی · DarsAI"))
        self.assertEqual(self.labels(self.markup(call)), [["🔙 تنظیمات"], ["🗑 پاک کردن داده‌هام"]][::-1])
        student.set_language(STUDENT, "en")
        run(privacy_ui.delete_command, text_update("/deletemydata"))
        call = self.reply_text.call_args
        self.assertTrue(call.args[0].startswith("🗑 Delete all your data?"))
        self.assertEqual(self.labels(self.markup(call)), [["🗑 Yes, delete everything"], ["Cancel"]])
        self.assertEqual(student.get_student(STUDENT)["language"], "en", "nothing deleted before the confirmation")

    def test_cancel_goes_back_to_the_policy(self):
        self.press(f"d1:{STUDENT}:priv:d")
        self.assertIn("It can't be undone.", self.shown()[0])
        self.press(f"d1:{STUDENT}:priv")
        self.assertTrue(self.shown()[0].startswith("🔒 Privacy"))

    def test_nobody_else_can_delete_your_data(self):
        student.set_language(STUDENT, "fa")
        self.press(f"d1:{STUDENT}:priv:d:y", user_id=OTHER, chat_type="supergroup")
        self.assertIn("someone else", self.answer.call_args.args[0])
        self.assertEqual(student.get_student(STUDENT)["language"], "fa")


class DeleteTests(TelegramMocks):
    """Fill every store for two students through the real screens, delete one, and check nothing of theirs is left."""

    def press(self, data, user_id=STUDENT, chat_type="private"):
        """A button press by user_id, in their own private chat (or the group)."""
        chat = {"id": user_id if chat_type == "private" else -1001, "type": chat_type}
        message = {"message_id": 5, "date": DATE, "chat": chat, "from": BOT_USER, "text": "previous screen"}
        query = {"id": "9", "from": _user(user_id, "en"), "chat_instance": "c",
                 "data": data.replace("{u}", str(user_id)), "message": message}
        run(router.callback_router, Update.de_json({"update_id": 2, "callback_query": query}, BOT))

    def type(self, text, user_id=STUDENT, **kwargs):
        run(typed.private_text, text_update(text, user_id=user_id, **kwargs))

    def use_everything(self, user_id):
        run(stats.track_activity, text_update("/start insta", user_id=user_id))
        run(home.start_command, text_update("/start", user_id=user_id))
        for route in ("su:l:fa", "su:v:middle_school", "su:c:math"):
            self.press(f"d1:{{u}}:{route}", user_id=user_id)
        self.press("d1:{u}:c:math:prac:n:linear_equations", user_id=user_id)
        question = shared.ACTIVE_QUESTION_FALLBACK[(user_id, user_id)]
        self.type(question["answer"], user_id=user_id)  # mastery and today's practice answers
        self.press("d1:{u}:c:math:prac:n:linear_equations", user_id=user_id)  # a new active question
        self.press("d1:{u}:c:math:prac:n:linear_equations", user_id=user_id, chat_type="supergroup")  # in a group too
        with patch.object(ai, "call_ai_provider", AsyncMock(return_value="An answer.")):
            self.press("d1:{u}:c:math:tutor", user_id=user_id)
            self.type("why?", user_id=user_id)  # tutor memory and usage
        self.press("d1:{u}:c:math:solve", user_id=user_id)  # an input mode
        self.press("d1:{u}:prem:a:photo:m", user_id=user_id)
        self.press("d1:{u}:c:physics:n", user_id=user_id)

    def stores_of(self, user_id):
        return {name: [k for k in store if user_of(k) == user_id] for name, store, user_of in privacy._MEMORY_STORES}

    def test_every_store_is_emptied_for_the_student_only(self):
        self.use_everything(STUDENT)
        self.use_everything(OTHER)
        before = self.stores_of(STUDENT)
        self.assertTrue(all(before.values()), {name: keys for name, keys in before.items() if not keys})
        self.assertIn(STUDENT, stats._seen)
        self.assertIn(STUDENT, setup._current)

        self.press(f"d1:{STUDENT}:priv:d")
        self.press(f"d1:{STUDENT}:priv:d:y")
        text = self.edit_text.call_args.args[0]
        self.assertTrue(text.startswith("✅ انجام شد."), "in the language they used")
        self.assertIsNone(self.markup(self.edit_text.call_args), "no buttons: they would start new records")

        # Only today's tutor-message count stays (the daily limit).
        self.assertEqual({name: keys for name, keys in self.stores_of(STUDENT).items() if keys},
                         {"ai._USAGE_FALLBACK": [(STUDENT, ai._today())]})
        self.assertNotIn(STUDENT, stats._seen)
        self.assertNotIn(STUDENT, setup._current)
        self.assertTrue(all(self.stores_of(OTHER).values()), "the other student keeps everything")

        # Afterwards they are new: /start asks the setup questions again, and /stats counts them as new.
        self.reply_text.reset_mock()
        run(stats.track_activity, text_update("/start", user_id=STUDENT))
        run(home.start_command, text_update("/start", user_id=STUDENT))
        self.assertIn("which language", self.reply_text.call_args.args[0])
        self.assertIsNone(activity._FIRST_SEEN[STUDENT]["source"], "the start link they came from is gone")

    def test_deleting_does_not_reset_the_daily_tutor_limit(self):
        from datetime import timedelta
        ai._USAGE_FALLBACK[(STUDENT, ai._today() - timedelta(days=1))] = 2
        for _ in range(config.FREE_DAILY_AI_LIMIT):
            ai.reserve_ai_message(STUDENT)
        with self.assertRaises(ai.AILimitReached):
            ai.reserve_ai_message(STUDENT)
        ai._USAGE_FALLBACK[(STUDENT, ai._today() - timedelta(days=1))] = 2  # reserve drops other days; put one back
        privacy.delete_student(STUDENT)
        with self.assertRaises(ai.AILimitReached):
            ai.reserve_ai_message(STUDENT)
        self.assertEqual([key for key in ai._USAGE_FALLBACK if key[0] == STUDENT], [(STUDENT, ai._today())])
        ai.reserve_ai_message(OTHER)  # others are not affected

    def test_delete_logs_counts_never_content(self):
        self.use_everything(STUDENT)
        with self.assertLogs("modules.privacy", "INFO") as logs:
            deleted = privacy.delete_student(STUDENT)
        self.assertGreater(deleted["ai._MEMORY_FALLBACK"], 0)
        self.assertIn(f"Deleted the data of user id {STUDENT}", logs.output[0])
        self.assertNotIn("why?", logs.output[0])
        with self.assertLogs("modules.privacy", "INFO") as logs:
            self.assertEqual(privacy.delete_student(STUDENT), {})
        self.assertIn("nothing was stored", logs.output[0])

    def test_the_application_forgets_the_student(self):
        application = MagicMock()
        privacy_ui.forget_in_process(SimpleNamespace(application=application), STUDENT)
        application.drop_user_data.assert_called_once_with(STUDENT)
        privacy_ui.forget_in_process(SimpleNamespace(), STUDENT)  # no application (tests): nothing to drop


class InventoryTests(TelegramMocks):
    def test_every_in_memory_store_is_listed(self):
        """A new module-level fallback dict must be added to privacy._MEMORY_STORES."""
        listed = {id(store) for _, store, _ in privacy._MEMORY_STORES}
        found = []
        for name, module in list(sys.modules.items()):
            if not name.startswith("modules.") or module is None:
                continue
            for attribute, value in vars(module).items():
                if isinstance(value, dict) and ("FALLBACK" in attribute or attribute == "_FIRST_SEEN"):
                    found.append((f"{name}.{attribute}", id(value)))
        self.assertTrue(found)
        missing = [name for name, identity in found if identity not in listed]
        self.assertEqual(missing, [])
