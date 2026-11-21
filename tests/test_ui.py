import asyncio
import re
import string
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup, Update
from telegram.ext import ExtBot

import main
from modules import ai, student
from modules.i18n import RTL_LANGUAGES, STRINGS, detect_language, local_digits, t
from modules.math.shared import get_user_level
from modules.ui import core, home, router

BOT = main.telegram_app.bot
STUDENT = 42
DATE = 1700000000  # date 0 would make Telegram objects "inaccessible messages"


def _chat(chat_type: str, user_id: int) -> dict:
    return {"id": user_id if chat_type == "private" else -1001, "type": chat_type}


def _user(user_id: int, language_code: str) -> dict:
    return {"id": user_id, "is_bot": False, "first_name": "Sara", "language_code": language_code}


def text_update(text: str, chat_type: str = "private", user_id: int = STUDENT, language_code: str = "en") -> Update:
    message = {"message_id": 1, "date": DATE, "chat": _chat(chat_type, user_id), "from": _user(user_id, language_code), "text": text}
    if text.startswith("/"):
        message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    return Update.de_json({"update_id": 1, "message": message}, BOT)


def button_update(data: str, user_id: int = STUDENT, chat_type: str = "private", language_code: str = "en", photo: bool = False) -> Update:
    owner_chat = _chat(chat_type, STUDENT)
    message = {"message_id": 5, "date": DATE, "chat": owner_chat, "from": {"id": 1, "is_bot": True, "first_name": "DarsAI"}}
    if photo:
        message["photo"] = [{"file_id": "p", "file_unique_id": "p", "width": 1, "height": 1}]
    else:
        message["text"] = "previous screen"
    query = {"id": "9", "from": _user(user_id, language_code), "chat_instance": "c", "data": data, "message": message}
    return Update.de_json({"update_id": 2, "callback_query": query}, BOT)


def run(handler, update: Update, args=None):
    context = SimpleNamespace(bot=BOT, args=args or [])
    asyncio.run(handler(update, context))


class TelegramMocks(unittest.TestCase):
    """Replaces every Telegram API call the interface makes, and resets in-memory storage."""

    def setUp(self):
        student._FALLBACK.clear()
        ai._MEMORY_FALLBACK.clear()
        self.reply_text = self._patch(Message, "reply_text")
        self.answer = self._patch(CallbackQuery, "answer")
        self.edit_text = self._patch(CallbackQuery, "edit_message_text")
        self.edit_markup = self._patch(CallbackQuery, "edit_message_reply_markup")
        self.send_message = self._patch(ExtBot, "send_message")

    def _patch(self, owner, name):
        mock = AsyncMock()
        patcher = patch.object(owner, name, mock)
        patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    @staticmethod
    def markup(call):
        return call.kwargs.get("reply_markup")

    @staticmethod
    def buttons(markup: InlineKeyboardMarkup):
        return [button for row in markup.inline_keyboard for button in row]


class CallbackDataTests(unittest.TestCase):
    def test_round_trip(self):
        data = core.pack(123, "set", "lvl", "pre_college")
        self.assertEqual(core.unpack(data), (123, ["set", "lvl", "pre_college"]))

    def test_fits_telegram_limit_with_a_long_user_id(self):
        self.assertLessEqual(len(core.pack(10 ** 15, "set", "lvl", "pre_college").encode()), 64)
        with self.assertRaises(ValueError):
            core.pack(1, "x" * 70)

    def test_ignores_other_buttons(self):
        for data in ("main:level", "math_level:high_school", "d1:abc:set", "d1:5", "", None):
            self.assertIsNone(core.unpack(data))


class TranslationTests(unittest.TestCase):
    def test_every_language_has_the_same_keys_and_placeholders(self):
        def placeholders(text):
            return {name for _, name, _, _ in string.Formatter().parse(text) if name}

        english = STRINGS["en"]
        for lang, strings in STRINGS.items():
            self.assertEqual(set(strings), set(english), f"{lang} keys differ from en")
            for key, text in strings.items():
                self.assertEqual(placeholders(text), placeholders(english[key]), f"{lang}:{key}")

    def test_commands_in_right_to_left_text_have_a_left_to_right_mark(self):
        # Without U+200E right before it, "/start" in a Persian sentence shows as "start/".
        bare_command = re.compile("(?<!\u200e)/[A-Za-z]")
        self.assertIsNotNone(bare_command.search("برای منوی خودت /start رو بفرست."))
        self.assertIsNone(bare_command.search("برای منوی خودت \u200e/start رو بفرست."))
        for lang in RTL_LANGUAGES:
            for key, text in STRINGS[lang].items():
                self.assertIsNone(bare_command.search(text), f"{lang}:{key} needs \\u200e before the /command")

    def test_language_detection_and_digits(self):
        self.assertEqual(detect_language("fa"), "fa")
        self.assertEqual(detect_language("fa-IR"), "fa")
        self.assertEqual(detect_language("en-US"), "en")
        self.assertEqual(detect_language(None), "en")
        self.assertEqual(local_digits("fa", 120), "۱۲۰")
        self.assertEqual(local_digits("en", 120), "120")

    def test_persian_keyboards_are_mirrored(self):
        self.assertEqual(core.arrange("fa", [[1, 2], [3]]), [[2, 1], [3]])
        self.assertEqual(core.arrange("en", [[1, 2], [3]]), [[1, 2], [3]])


class StartTests(TelegramMocks):
    def test_private_start_adds_menu_button_then_main_menu(self):
        run(home.start_command, text_update("/start"))
        welcome, menu = self.reply_text.call_args_list
        self.assertIsInstance(self.markup(welcome), ReplyKeyboardMarkup)
        self.assertEqual(self.markup(welcome).keyboard[0][0].text, "🏠 Menu")
        buttons = self.buttons(self.markup(menu))
        self.assertEqual(len(buttons), 7)
        self.assertTrue(all(b.callback_data.startswith(f"d1:{STUDENT}:") for b in buttons))
        self.assertIn("High School", menu.args[0])

    def test_persian_telegram_users_get_persian(self):
        run(home.start_command, text_update("/start", language_code="fa"))
        welcome, menu = self.reply_text.call_args_list
        self.assertIn("خوش اومدی", welcome.args[0])
        self.assertIn("متوسطه دوم (دهم و یازدهم)", menu.args[0])
        # Mirrored: the first button (Learn) sits on the right.
        self.assertEqual(self.markup(menu).inline_keyboard[0][1].text, t("fa", "btn.learn"))

    def test_group_start_has_no_bottom_button_and_names_the_owner(self):
        run(home.start_command, text_update("/start", chat_type="supergroup"))
        (menu,) = self.reply_text.call_args_list
        self.assertIsInstance(self.markup(menu), InlineKeyboardMarkup)
        self.assertIn("👤 Sara", menu.args[0])

    def test_menu_button_and_other_text(self):
        run(home.text_message, text_update("🏠 منو"))
        self.assertNotIn(t("en", "home.hint"), self.reply_text.call_args.args[0])
        run(home.text_message, text_update("hello"))
        self.assertIn(t("en", "home.hint"), self.reply_text.call_args.args[0])


class ButtonTests(TelegramMocks):
    def press(self, data, **kwargs):
        run(router.callback_router, button_update(data, **kwargs))

    def test_settings_edits_the_same_message(self):
        self.press(f"d1:{STUDENT}:set")
        self.assertIn("Settings", self.edit_text.call_args.args[0])
        self.send_message.assert_not_called()
        self.answer.assert_called_once()

    def test_other_people_cannot_press_your_buttons(self):
        self.press(f"d1:{STUDENT}:set", user_id=7, chat_type="supergroup")
        self.edit_text.assert_not_called()
        self.assertIn("someone else", self.answer.call_args.args[0])

    def test_unbuilt_screens_say_coming_soon(self):
        self.press(f"d1:{STUDENT}:prac")
        self.edit_text.assert_not_called()
        self.assertIn("Coming soon", self.answer.call_args.args[0])

    def test_switching_to_persian(self):
        self.press(f"d1:{STUDENT}:set:lang:fa")
        self.assertEqual(student.get_student(STUDENT)["language"], "fa")
        self.assertIn("تنظیمات", self.edit_text.call_args.args[0])
        # A new message updates the bottom Menu button to the new language.
        sent = self.send_message.call_args
        self.assertEqual(self.markup(sent).keyboard[0][0].text, "🏠 منو")

    def test_level_is_saved_for_every_chat(self):
        self.press(f"d1:{STUDENT}:set:lvl:university", chat_type="supergroup")
        self.assertEqual(get_user_level(-1001, STUDENT), "university")
        self.assertEqual(get_user_level(STUDENT, STUDENT), "university")
        self.assertIn("University", self.edit_text.call_args.args[0])

    def test_unknown_level_shows_the_picker(self):
        self.press(f"d1:{STUDENT}:set:lvl:wizard")
        self.assertEqual(get_user_level(STUDENT, STUDENT), "high_school")
        labels = [b.text for b in self.buttons(self.markup(self.edit_text.call_args))]
        self.assertIn("High School ✓", labels)

    def test_clear_memory_asks_first(self):
        ai.save_exchange(STUDENT, STUDENT, "quadratics", "q", "a")
        self.press(f"d1:{STUDENT}:set:clr")
        self.assertEqual(len(ai.load_history(STUDENT, STUDENT, "quadratics")), 2)
        self.press(f"d1:{STUDENT}:set:clr:y")
        self.assertEqual(ai.load_history(STUDENT, STUDENT, "quadratics"), [])
        self.assertIn("2", self.answer.call_args.args[0])

    def test_photo_messages_get_a_new_message(self):
        self.press(f"d1:{STUDENT}:home", photo=True)
        self.edit_text.assert_not_called()
        self.edit_markup.assert_called_once()
        self.assertIn("What would you like to do?", self.send_message.call_args.args[1])


class CommandMenuTests(unittest.TestCase):
    def test_only_start_and_help(self):
        with patch.object(ExtBot, "set_my_commands", AsyncMock()) as set_commands:
            asyncio.run(main.setup_bot_commands())
        self.assertEqual(set_commands.call_count, 2)
        for call in set_commands.call_args_list:
            self.assertEqual([c.command for c in call.args[0]], ["start", "help"])
        persian = next(c for c in set_commands.call_args_list if c.kwargs["language_code"] == "fa")
        self.assertTrue(re.search("[؀-ۿ]", persian.args[0][0].description))
