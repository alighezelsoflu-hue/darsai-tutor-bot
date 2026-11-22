import asyncio
import json
import re
import string
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import BotDescription, BotShortDescription, CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup, Update
from telegram.error import TimedOut
from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ExtBot

import main
from modules import activity, ai, courses, input_mode, notify, premium, stats, student
from modules.i18n import RTL_LANGUAGES, STRINGS, detect_language, local_digits, t
from modules.math import math as math_commands
from modules.math import shared
from modules.math.shared import get_mastery, get_user_level, next_mastery, record_answer
from modules.ui import core, groups, home, practice, router, setup, tools, typed

BOT = main.telegram_app.bot
STUDENT = 42
DATE = 1700000000  # date 0 would make Telegram objects "inaccessible messages"


def _chat(chat_type: str, user_id: int) -> dict:
    return {"id": user_id if chat_type == "private" else -1001, "type": chat_type}


def _user(user_id: int, language_code: str) -> dict:
    return {"id": user_id, "is_bot": False, "first_name": "Sara", "language_code": language_code}


BOT_USER = {"id": 1, "is_bot": True, "first_name": "DarsAI"}


def text_update(text: str, chat_type: str = "private", user_id: int = STUDENT, language_code: str = "en", reply_to=None) -> Update:
    chat = _chat(chat_type, user_id)
    message = {"message_id": 1, "date": DATE, "chat": chat, "from": _user(user_id, language_code), "text": text}
    if text.startswith("/"):
        message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    if reply_to is not None:
        message["reply_to_message"] = {"message_id": reply_to, "date": DATE, "chat": chat, "from": BOT_USER, "text": "question"}
    return Update.de_json({"update_id": 1, "message": message}, BOT)


def button_update(data: str, user_id: int = STUDENT, chat_type: str = "private", language_code: str = "en", photo: bool = False, topic=None) -> Update:
    owner_chat = _chat(chat_type, STUDENT)
    message = {"message_id": 5, "date": DATE, "chat": owner_chat, "from": BOT_USER}
    if topic is not None:
        owner_chat["is_forum"] = True
        message.update(message_thread_id=topic, is_topic_message=True)
    if photo:
        message["photo"] = [{"file_id": "p", "file_unique_id": "p", "width": 1, "height": 1}]
    else:
        message["text"] = "previous screen"
    query = {"id": "9", "from": _user(user_id, language_code), "chat_instance": "c", "data": data, "message": message}
    return Update.de_json({"update_id": 2, "callback_query": query}, BOT)


def code_texts(call, text_key=None):
    """The parts of a sent message that Telegram shows as code (one tap copies them)."""
    text = call.args[0] if text_key is None else call.kwargs[text_key]
    entities = call.kwargs.get("entities" if text_key is None else "caption_entities") or []
    units = text.encode("utf-16-le")
    return [units[2 * e.offset:2 * (e.offset + e.length)].decode("utf-16-le") for e in entities if e.type == "code"]


def math_routes(buttons):
    """{label: route} without the "c:math:" every Math screen's route starts with."""
    routes = {}
    for button in buttons:
        route = button.callback_data.split(":", 2)[2]
        routes[button.text] = route[len("c:math:"):] if route.startswith("c:math:") else route
    return routes


def run(handler, update: Update, args=None):
    context = SimpleNamespace(bot=BOT, args=args or [])
    asyncio.run(handler(update, context))


class TelegramMocks(unittest.TestCase):
    """Replaces every Telegram API call the interface makes, and resets in-memory storage."""

    def setUp(self):
        student._FALLBACK.clear()
        ai._MEMORY_FALLBACK.clear()
        shared.MASTERY_FALLBACK.clear()
        shared.ACTIVE_QUESTION_FALLBACK.clear()
        input_mode._FALLBACK.clear()
        ai._USAGE_FALLBACK.clear()
        activity._FALLBACK.clear()
        activity._FIRST_SEEN.clear()
        premium._FALLBACK.clear()
        notify._FALLBACK.clear()
        stats._seen.clear()
        setup._current.clear()
        # Sent messages get ids 77 (replies) and 78 (new messages). Edited ones keep 5.
        self.reply_text = self._patch(Message, "reply_text", SimpleNamespace(message_id=77))
        self.answer = self._patch(CallbackQuery, "answer")
        self.edit_text = self._patch(CallbackQuery, "edit_message_text")
        self.edit_markup = self._patch(CallbackQuery, "edit_message_reply_markup")
        self.send_message = self._patch(ExtBot, "send_message", SimpleNamespace(message_id=78))
        self.bot_edit_markup = self._patch(ExtBot, "edit_message_reply_markup")
        self.reply_photo = self._patch(Message, "reply_photo", SimpleNamespace(message_id=79))
        self.send_photo = self._patch(ExtBot, "send_photo", SimpleNamespace(message_id=80))
        self.chat_action = self._patch(ExtBot, "send_chat_action")

    @staticmethod
    def existing_student(user_id: int = STUDENT) -> None:
        """A student who has done setup (or was there before it existed) and has the current bottom keyboard."""
        student.finish_setup(user_id, setup.KEYBOARD_VERSION)

    def _patch(self, owner, name, returns=None):
        mock = AsyncMock(return_value=returns)
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


class CodeEntityTests(unittest.TestCase):
    def test_marked_text_becomes_code_entities_in_utf16_units(self):
        text, entities = core.with_entities("📈 " + core.copyable("y = x^2") + "\n\u200e" + core.copyable("sin(x)"))
        self.assertEqual(text, "📈 y = x^2\n\u200esin(x)")
        self.assertEqual([(e.type, e.offset, e.length) for e in entities], [("code", 3, 7), ("code", 12, 6)])
        self.assertEqual(core.with_entities("plain"), ("plain", None))

    def test_marks_typed_by_a_student_cannot_break_entities(self):
        text, entities = core.with_entities("= " + core.copyable("2x\ue001 + \ue000 1"))
        self.assertEqual(text, "= 2x +  1")
        self.assertEqual([(e.offset, e.length) for e in entities], [(2, 7)])
        self.assertEqual(core.copyable("\ue000\ue001"), "")


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
    def test_private_start_adds_the_bottom_keyboard_then_home(self):
        self.existing_student()
        run(home.start_command, text_update("/start"))
        welcome, menu = self.reply_text.call_args_list
        self.assertIsInstance(self.markup(welcome), ReplyKeyboardMarkup)
        self.assertEqual([b.text for b in self.markup(welcome).keyboard[0]], ["🏠 Menu", "▶️ Continue"])
        self.assertIn("▶️ Continue takes you back to where you were", welcome.args[0])
        buttons = self.buttons(self.markup(menu))
        self.assertEqual(len(buttons), 11)
        self.assertTrue(all(b.callback_data.startswith(f"d1:{STUDENT}:") for b in buttons))
        self.assertTrue(menu.args[0].startswith("DarsAI 🎓 · Grades 10–11\n\nChoose a course to start:"))

    def test_persian_telegram_users_get_persian(self):
        self.existing_student()
        run(home.start_command, text_update("/start", language_code="fa"))
        welcome, menu = self.reply_text.call_args_list
        self.assertIn("خوش اومدی", welcome.args[0])
        # Mirrored: 🏠 منو sits on the right.
        self.assertEqual([b.text for b in self.markup(welcome).keyboard[0]], ["▶️ ادامه", "🏠 منو"])
        self.assertIn("منوی اصلی DarsAI 🎓 · دهم و یازدهم", menu.args[0])
        # Mirrored: the first course (Math) sits on the right.
        self.assertEqual(self.markup(menu).inline_keyboard[1][1].text, "📐 ریاضی")

    def test_group_start_has_no_bottom_button_and_names_the_owner(self):
        run(home.start_command, text_update("/start", chat_type="supergroup"))
        (menu,) = self.reply_text.call_args_list
        self.assertIsInstance(self.markup(menu), InlineKeyboardMarkup)
        self.assertIn("👤 Sara", menu.args[0])

    def test_menu_button_and_other_text(self):
        run(typed.private_text, text_update("🏠 منو"))
        self.assertNotIn(t("en", "home.hint"), self.reply_text.call_args.args[0])
        run(typed.private_text, text_update("hello"))
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
        self.press(f"d1:{STUDENT}:guide")
        self.edit_text.assert_not_called()
        self.assertIn("Coming soon", self.answer.call_args.args[0])

    def test_switching_to_persian(self):
        self.press(f"d1:{STUDENT}:set:lang:fa")
        self.assertEqual(student.get_student(STUDENT)["language"], "fa")
        self.assertIn("تنظیمات", self.edit_text.call_args.args[0])
        # A new message updates the bottom Menu button to the new language.
        sent = self.send_message.call_args
        self.assertEqual([b.text for b in self.markup(sent).keyboard[0]], ["▶️ ادامه", "🏠 منو"])

    def test_level_is_saved_for_every_chat(self):
        self.press(f"d1:{STUDENT}:set:lvl:university", chat_type="supergroup")
        self.assertEqual(get_user_level(-1001, STUDENT), "university")
        self.assertEqual(get_user_level(STUDENT, STUDENT), "university")
        self.assertIn("University", self.edit_text.call_args.args[0])

    def test_unknown_level_shows_the_picker(self):
        self.press(f"d1:{STUDENT}:set:lvl:wizard")
        self.assertEqual(get_user_level(STUDENT, STUDENT), "high_school")
        labels = [b.text for b in self.buttons(self.markup(self.edit_text.call_args))]
        self.assertIn("Grades 10–11 ✓", labels)

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
        self.assertIn("DarsAI 🎓 · Grades 10–11", self.send_message.call_args.args[1])


class PracticeTests(TelegramMocks):
    GROUP = -1001

    def press(self, data, **kwargs):
        run(router.callback_router, button_update(data, **kwargs))

    def type(self, text, **kwargs):
        run(typed.private_text, text_update(text, **kwargs))

    def question(self, chat_id=STUDENT):
        return shared.ACTIVE_QUESTION_FALLBACK.get((chat_id, STUDENT))

    def wrong_answer(self, question):
        return "1000" if question["answer"].count(",") == 0 else "1000, 2000"

    def last_reply(self):
        call = self.reply_text.call_args
        return call.args[0], self.markup(call)

    def routes(self, markup):
        return math_routes(self.buttons(markup))

    def test_practice_lists_the_topics_of_the_level(self):
        record_answer(STUDENT, "high_school", "algebra", "easy", "first_try")
        self.press(f"d1:{STUDENT}:prac")
        text = self.edit_text.call_args.args[0]
        self.assertTrue(text.startswith("✍️ Math · Grades 10–11\nPick a topic:\n"))
        self.assertIn("Equations with brackets: ▰▰▱▱▱▱▱▱▱▱ 18%", text)
        self.assertIn("Quadratic equations: not started yet", text)
        routes = self.routes(self.markup(self.edit_text.call_args))
        self.assertEqual(routes["Equations with brackets"], "prac:n:algebra")
        self.assertEqual(routes["🔙 Math"], "c:math")

    def test_a_topic_opens_an_easy_question_in_the_same_message(self):
        self.press(f"d1:{STUDENT}:prac:n:quadratics")
        text = self.edit_text.call_args.args[0]
        q = self.question()
        self.assertEqual((q["topic"], q["difficulty"], q["mode"], q["attempts"]), ("quadratics", "easy", "a", 0))
        self.assertEqual(q["message_ids"], [5])
        self.assertIn("Quadratic equations · 🟢 Easy", text)
        self.assertIn(q["formula"][0], text)
        self.assertIn("Type your answer", text)
        self.assertIn("two answers", text)
        routes = self.routes(self.markup(self.edit_text.call_args))
        self.assertEqual(routes["💡 Show solution"], f"prac:s:{q['id']}")
        self.assertEqual(routes["⏭ Skip"], "prac:n:quadratics:a")

    def test_correct_typed_answer(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra")
        q = self.question()
        self.type(f"x = {q['answer']}")
        text, markup = self.last_reply()
        self.assertTrue(text.startswith("✅ Correct!"))
        self.assertIn("How to solve it", text)
        self.assertIn(q["steps"][-1][2], text)
        self.assertIn("Equations with brackets: ▰▰▱▱▱▱▱▱▱▱ 18% (↑18)", text)
        self.assertIsNone(self.question())
        self.assertEqual(get_mastery(STUDENT)[("high_school", "algebra")]["correct"], 1)
        routes = self.routes(markup)
        self.assertEqual(routes["➡️ Next question"], "prac:n:algebra:a")
        self.assertEqual(routes["🔼 Harder"], "prac:n:algebra:m")
        self.assertNotIn("🔽 Easier", routes)

    def buttons_removed_from(self):
        return [call.kwargs["message_id"] for call in self.bot_edit_markup.call_args_list]

    def test_typed_answer_removes_the_question_buttons(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra")
        q = self.question()
        self.type("I don't know")  # hint message 77
        self.type(self.wrong_answer(q))  # retry message 77 again (the mock always returns 77)
        self.assertEqual(self.question()["message_ids"], [5, 77, 77])
        self.bot_edit_markup.assert_not_called()
        self.type(q["answer"])
        self.assertEqual(self.buttons_removed_from(), [5, 77, 77])
        self.assertTrue(all(call.kwargs["reply_markup"] is None for call in self.bot_edit_markup.call_args_list))

    def test_show_solution_on_the_retry_message_removes_the_question_buttons(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra")
        q = self.question()
        shared.ACTIVE_QUESTION_FALLBACK[(STUDENT, STUDENT)]["message_ids"] = [3]  # the question was message 3
        self.type(self.wrong_answer(q))  # retry message 77
        run(router.callback_router, button_update(f"d1:{STUDENT}:prac:s:{q['id']}"))  # pressed on message 5
        self.assertEqual(self.buttons_removed_from(), [3, 77])

    def test_a_finished_question_never_comes_back(self):
        # The student types a first wrong answer while Show solution finishes the question.
        self.press(f"d1:{STUDENT}:prac:n:algebra")
        stale = self.question()
        self.press(f"d1:{STUDENT}:prac:s:{stale['id']}")
        screen = asyncio.run(core.Screen.load(text_update("1000"), SimpleNamespace(bot=BOT)))
        asyncio.run(practice.handle_answer(screen, stale, self.wrong_answer(stale)))
        self.assertIsNone(self.question())
        self.assertIn(77, self.buttons_removed_from(), "the stale retry message loses its button")
        asyncio.run(practice.handle_answer(screen, dict(stale, attempts=1), self.wrong_answer(stale)))
        self.assertEqual(get_mastery(STUDENT)[("high_school", "algebra")]["wrong"], 1, "counted once")

    def test_a_replaced_question_is_not_overwritten(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra")
        stale = self.question()
        self.press(f"d1:{STUDENT}:prac:n:algebra")  # Skip: a new question
        new = self.question()
        screen = asyncio.run(core.Screen.load(text_update("1000"), SimpleNamespace(bot=BOT)))
        asyncio.run(practice.handle_answer(screen, stale, self.wrong_answer(stale)))
        self.assertEqual(self.question(), new)

    def test_one_more_try_then_the_solution(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra")
        q = self.question()
        self.type(self.wrong_answer(q))
        text, markup = self.last_reply()
        self.assertIn("Try once more", text)
        self.assertEqual(self.question()["attempts"], 1)
        self.assertEqual(self.routes(markup), {"💡 Show solution": f"prac:s:{q['id']}"})
        self.type(self.wrong_answer(q))
        text, _ = self.last_reply()
        self.assertTrue(text.startswith("❌ Not this time"))
        self.assertIn(q["steps"][-1][2], text)
        self.assertIsNone(self.question())
        self.assertEqual(get_mastery(STUDENT)[("high_school", "algebra")]["wrong"], 1)

    def test_right_on_the_second_try(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra")
        q = self.question()
        self.type(self.wrong_answer(q))
        self.type(q["answer"])
        text, _ = self.last_reply()
        self.assertTrue(text.startswith("✅ Correct on the second try!"))
        expected = next_mastery(0.0, "easy", "second_try")
        self.assertAlmostEqual(get_mastery(STUDENT)[("high_school", "algebra")]["mastery"], expected)

    def test_text_that_is_not_an_answer_does_not_use_a_try(self):
        self.press(f"d1:{STUDENT}:prac:n:quadratics")
        self.type("I don't know")
        text, _ = self.last_reply()
        self.assertIn("couldn't read that", text)
        self.assertIn("2, -3", text)
        self.assertEqual(self.question()["attempts"], 0)

    def test_answer_hints_are_copyable(self):
        self.press(f"d1:{STUDENT}:prac:n:quadratics")
        self.assertEqual(code_texts(self.edit_text.call_args), ["2, -3"])
        self.type("I don't know")
        self.assertEqual(code_texts(self.reply_text.call_args), ["2, -3"])

    def test_roots_on_two_lines_are_one_answer(self):
        self.press(f"d1:{STUDENT}:prac:n:quadratics")
        r1, r2 = self.question()["answer"].split(",")
        self.type(f"x = {r1}\nx = {r2}")
        self.assertTrue(self.last_reply()[0].startswith("✅ Correct!"))

    def test_a_quadratic_answer_with_one_root_gets_the_two_answers_hint(self):
        self.press(f"d1:{STUDENT}:prac:n:quadratics")
        self.type(self.question()["answer"].split(",")[0])
        self.assertIn("two answers", self.last_reply()[0])

    def test_show_solution_counts_as_missed_and_only_once(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra")
        q = self.question()
        self.press(f"d1:{STUDENT}:prac:s:{q['id']}")
        text = self.edit_text.call_args.args[0]
        self.assertIn(q["formula"][0], text)
        self.assertIn("How to solve it", text)
        self.assertIn("➡️ Next question", self.routes(self.markup(self.edit_text.call_args)))
        self.assertEqual(get_mastery(STUDENT)[("high_school", "algebra")]["wrong"], 1)
        edits = self.edit_text.call_count
        self.press(f"d1:{STUDENT}:prac:s:{q['id']}")
        self.assertEqual(self.edit_text.call_count, edits)
        self.assertIn("already finished", self.answer.call_args.args[0])
        self.assertEqual(get_mastery(STUDENT)[("high_school", "algebra")]["wrong"], 1)

    def test_difficulty_follows_mastery_until_the_student_picks_one(self):
        for _ in range(8):
            record_answer(STUDENT, "high_school", "algebra", "hard", "first_try")
        self.press(f"d1:{STUDENT}:prac:n:algebra")
        self.assertEqual(self.question()["difficulty"], "hard")
        self.press(f"d1:{STUDENT}:prac:n:algebra:e")
        q = self.question()
        self.assertEqual((q["difficulty"], q["mode"]), ("easy", "e"))
        self.type(q["answer"])
        _, markup = self.last_reply()
        self.assertEqual(self.routes(markup)["➡️ Next question"], "prac:n:algebra:e")

    def test_says_when_the_next_questions_get_harder(self):
        # Answer easy questions until one more correct answer would make the next one medium.
        mastery = 0.0
        while shared.recommended_difficulty(next_mastery(mastery, "easy", "first_try")) == "easy":
            record_answer(STUDENT, "middle_school", "linear_equations", "easy", "first_try")
            mastery = next_mastery(mastery, "easy", "first_try")
        self.press(f"d1:{STUDENT}:prac:n:linear_equations")
        self.type(self.question()["answer"])
        self.assertIn("Next questions: 🟡 Medium", self.last_reply()[0])

    def test_menu_button_keeps_the_question(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra")
        self.type("🏠 Menu")
        self.assertIn("Pick up where you left off", self.last_reply()[0])
        self.assertIsNotNone(self.question())

    def test_typed_text_after_a_day_opens_the_menu(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra")
        shared.ACTIVE_QUESTION_FALLBACK[(STUDENT, STUDENT)]["asked_at"] = time.time() - 25 * 3600
        self.type("5")
        self.assertIn(t("en", "home.hint"), self.last_reply()[0])

    def test_groups_answer_by_replying_to_the_question(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra", chat_type="supergroup")
        q = self.question(self.GROUP)
        text = self.edit_text.call_args.args[0]
        self.assertIn("👤 Sara", text)
        self.assertIn("Reply to this message", text)

        reply = text_update(q["answer"], chat_type="supergroup", reply_to=5)
        handler = next(h for h in main.telegram_app.handlers[0] if getattr(h, "callback", None) is typed.group_reply)
        self.assertTrue(handler.check_update(reply))
        self.assertFalse(handler.check_update(text_update(q["answer"], chat_type="supergroup")))

        # A reply to another message, or by someone else, is not an answer.
        run(typed.group_reply, text_update(q["answer"], chat_type="supergroup", reply_to=99))
        run(typed.group_reply, text_update(q["answer"], chat_type="supergroup", user_id=7, reply_to=5))
        self.reply_text.assert_not_called()

        run(typed.group_reply, reply)
        self.assertTrue(self.last_reply()[0].startswith("✅ Correct!"))

    def test_group_retry_message_also_takes_replies(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra", chat_type="supergroup")
        q = self.question(self.GROUP)
        run(typed.group_reply, text_update(self.wrong_answer(q), chat_type="supergroup", reply_to=5))
        self.assertIn("Reply to this message with your new answer", self.last_reply()[0])
        self.assertEqual(self.question(self.GROUP)["message_ids"], [5, 77])
        run(typed.group_reply, text_update(q["answer"], chat_type="supergroup", reply_to=77))
        self.assertTrue(self.last_reply()[0].startswith("✅ Correct on the second try!"))

    def test_mastery_follows_the_student_into_other_chats(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra", chat_type="supergroup")
        run(typed.group_reply, text_update(self.question(self.GROUP)["answer"], chat_type="supergroup", reply_to=5))
        self.press(f"d1:{STUDENT}:prac")
        self.assertIn("Equations with brackets: ▰▰▱▱▱▱▱▱▱▱ 18%", self.edit_text.call_args.args[0])

    def test_persian_formulas_sit_on_their_own_left_to_right_lines(self):
        student.set_language(STUDENT, "fa")
        self.press(f"d1:{STUDENT}:prac:n:quadratics")
        q = self.question()
        self.type(q["answer"].replace(",", "، "))
        self.assertIn("\u200e" + q["formula"][0], self.edit_text.call_args.args[0])
        self.assertIn("\u200e" + q["steps"][-1][2], self.last_reply()[0])
        for text in (self.edit_text.call_args.args[0], self.last_reply()[0]):
            for line in text.splitlines():
                if re.search("[A-Za-z0-9]", line):
                    self.assertTrue(line.startswith("\u200e"), line)
        self.assertTrue(self.last_reply()[0].startswith("✅ درسته!"))
        self.assertIn("۱۸٪", self.last_reply()[0])

    def test_old_practice_and_check_commands(self):
        run(math_commands.practice_command, text_update("/practice high_school quadratics hard"), args=["high_school", "quadratics", "hard"])
        q = self.question()
        self.assertEqual((q["topic"], q["difficulty"], q["mode"]), ("quadratics", "hard", "h"))
        self.assertIn("🔴 Hard", self.last_reply()[0])
        self.assertEqual(q["message_ids"], [77])
        run(math_commands.check_command, text_update("/check 1000, 2000"), args=["1000,", "2000"])
        self.assertIn("Try once more", self.last_reply()[0])
        run(math_commands.check_command, text_update("/check " + q["answer"]), args=[q["answer"]])
        self.assertTrue(self.last_reply()[0].startswith("✅ Correct on the second try!"))
        run(math_commands.check_command, text_update("/check 5"), args=["5"])
        self.assertIn("No active practice question", self.last_reply()[0])

    def test_callback_data_fits_with_the_longest_routes(self):
        big = 10 ** 15
        core.pack(big, *practice.MATH, "prac", "n", "linear_equations", "a")
        core.pack(big, *practice.MATH, "prac", "s", "0123abcd")
        core.pack(big, *practice.MATH, "solve", "x", "0123abcd")
        core.pack(big, *practice.MATH, "konkur", "n")
        for course in courses.COURSES:
            core.pack(big, "su", "c", course)
            core.pack(big, "c", course, "n")


class StepFiveTests(TelegramMocks):
    """Learn, Ask the tutor, Solve, Plot and My progress."""

    GROUP = -1001

    def setUp(self):
        super().setUp()
        self.provider = AsyncMock(return_value="Step 1: think. Step 2: solve.")
        patcher = patch.object(ai, "call_ai_provider", self.provider)
        patcher.start()
        self.addCleanup(patcher.stop)

    def press(self, data, **kwargs):
        run(router.callback_router, button_update(data, **kwargs))

    def type(self, text, **kwargs):
        run(typed.private_text, text_update(text, **kwargs))

    def mode(self, chat_id=STUDENT):
        return input_mode.get_input_mode(chat_id, STUDENT)

    def shown(self):
        return self.edit_text.call_args.args[0]

    def last_reply(self):
        call = self.reply_text.call_args
        return call.args[0], self.markup(call)

    def routes(self, markup):
        return math_routes(self.buttons(markup))

    def test_main_menu_has_no_coming_soon_entries(self):
        for route in ("learn", "prac", "tutor", "solve", "plot", "prog", "set", "prem"):
            self.answer.reset_mock()
            self.press(f"d1:{STUDENT}:{route}")
            self.assertNotIn("Coming soon", str(self.answer.call_args))

    # ---------------------------------------------------------------- Learn

    def test_learn_topics_and_lesson(self):
        self.press(f"d1:{STUDENT}:learn")
        self.assertEqual(self.shown(), "📘 Math · Grades 10–11\nPick a topic:")
        self.assertEqual(self.routes(self.markup(self.edit_text.call_args))["Quadratic equations"], "learn:quadratics")
        self.press(f"d1:{STUDENT}:learn:quadratics")
        text = self.shown()
        for expected in ("📘 Math · Grades 10–11 › Quadratic equations\n", "ax^2 + bx + c = 0", "Example:", "x^2 - 5x + 6 = 0", "How to solve it", "x = 2, x = 3"):
            self.assertIn(expected, text)
        routes = self.routes(self.markup(self.edit_text.call_args))
        self.assertEqual(routes["✍️ Practice this"], "prac:n:quadratics")
        self.assertEqual(routes["🧑‍🏫 Ask the tutor"], "tutor:quadratics")
        self.assertEqual(routes["📚 Lessons"], "learn")
        self.assertEqual(routes["🔙 Math"], "c:math")

    def test_every_lesson_renders_in_both_languages(self):
        for lang in ("en", "fa"):
            student.set_language(STUDENT, lang)
            for topic in shared_topics():
                self.press(f"d1:{STUDENT}:learn:{topic}")
                text = self.shown()
                if lang == "fa":
                    for line in text.splitlines():
                        if re.search("[A-Za-z0-9]", line):
                            self.assertTrue(line.startswith("\u200e"), f"{topic}: {line}")

    def test_old_lesson_command_uses_the_lesson_screen(self):
        run(math_commands.lesson_command, text_update("/lesson university calculus"), args=["university", "calculus"])
        text, markup = self.last_reply()
        self.assertTrue(text.startswith("📘 Math · University › Derivatives\n"))
        self.assertIn("f'(x) = 6x + 5", text)

    # ---------------------------------------------------------------- Ask the tutor

    def test_tutor_answers_typed_questions_and_keeps_listening(self):
        self.press(f"d1:{STUDENT}:tutor")
        self.assertTrue(self.shown().startswith("🧑‍🏫 Ask the tutor · Math · Grades 10–11\nType any math question"))
        self.assertEqual(self.mode()["mode"], "tutor")
        self.type("why is x^0 = 1?")
        text, markup = self.last_reply()
        self.assertTrue(text.startswith("Step 1: think."))
        self.assertIn("Type another question", text)
        self.assertEqual(self.routes(markup), {"🔙 Math": "c:math"})
        self.chat_action.assert_called()
        self.assertEqual(ai.load_history(STUDENT, STUDENT, "math")[-2]["content"], "why is x^0 = 1?")
        self.type("and x^1?")
        self.assertEqual(self.provider.call_count, 2)
        history = self.provider.call_args.args[0]
        self.assertIn("why is x^0 = 1?", [m["content"] for m in history], "the tutor remembers the conversation")

    def test_tutor_from_a_lesson_uses_that_topic_and_the_student_language(self):
        student.set_language(STUDENT, "fa")
        self.press(f"d1:{STUDENT}:tutor:quadratics")
        self.assertTrue(self.shown().startswith("🧑‍🏫 از معلم بپرس · ریاضی · دهم و یازدهم › معادله‌ی درجه دوم\n"))
        self.type("دلتا چیه؟")
        system = self.provider.call_args.args[0][0]["content"]
        self.assertIn("Respond in Persian/Farsi", system)
        self.assertIn("own line", system)
        self.assertEqual(len(ai.load_history(STUDENT, STUDENT, "quadratics")), 2)

    def test_tutor_limit_and_errors_are_translated_and_hide_details(self):
        self.press(f"d1:{STUDENT}:tutor")
        for _ in range(3):  # FREE_DAILY_AI_LIMIT=3 in tests
            self.type("question")
        self.type("one more")
        self.assertIn("all 3 tutor messages", self.last_reply()[0])
        ai._USAGE_FALLBACK.clear()
        self.provider.side_effect = ai.AIProviderError("GROQ_API_KEY is missing")
        with self.assertLogs("modules.ai", "ERROR"):
            self.type("question")
        text = self.last_reply()[0]
        self.assertIn("isn't available", text)
        self.assertNotIn("GROQ", text)

    def test_long_tutor_answers_are_split(self):
        self.provider.return_value = "word " * 1500
        self.press(f"d1:{STUDENT}:tutor")
        self.type("explain everything")
        self.assertEqual(self.reply_text.call_count, 2)
        first, last = self.reply_text.call_args_list
        self.assertIsNone(self.markup(first))
        self.assertIsNotNone(self.markup(last))

    def test_menu_leaves_the_tool_and_practice_takes_over_again(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra")
        question = shared.ACTIVE_QUESTION_FALLBACK[(STUDENT, STUDENT)]
        self.press(f"d1:{STUDENT}:solve")
        self.type("2x + 5 = 17")
        self.assertIn("x = 6", self.last_reply()[0], "typed text goes to Solve while it is open")
        self.type("🏠 Menu")
        self.assertIsNone(self.mode())
        self.type(question["answer"])
        self.assertTrue(self.last_reply()[0].startswith("✅ Correct!"), "then it answers the practice question")

    def test_a_new_practice_question_closes_the_tool(self):
        self.press(f"d1:{STUDENT}:tutor")
        self.press(f"d1:{STUDENT}:prac:n:algebra")
        self.assertIsNone(self.mode())
        self.press(f"d1:{STUDENT}:plot")
        self.press(f"d1:{STUDENT}:home")
        self.assertIsNone(self.mode())

    def test_tool_mode_ends_after_a_day(self):
        self.press(f"d1:{STUDENT}:solve")
        input_mode._FALLBACK[(STUDENT, STUDENT)]["asked_at"] = time.time() - 25 * 3600
        self.type("2x = 4")
        self.assertIn(t("en", "home.hint"), self.last_reply()[0])

    def test_groups_use_replies_for_tools(self):
        self.press(f"d1:{STUDENT}:tutor", chat_type="supergroup")
        self.assertIn("Reply to this message with your question", self.shown())
        self.assertIn("👤 Sara", self.shown())
        run(typed.group_reply, text_update("hi", chat_type="supergroup", reply_to=99))
        run(typed.group_reply, text_update("hi", chat_type="supergroup", user_id=7, reply_to=5))
        self.provider.assert_not_called()
        run(typed.group_reply, text_update("what is a slope?", chat_type="supergroup", reply_to=5))
        self.assertIn("Reply to this message to ask more", self.last_reply()[0])
        self.assertEqual(self.mode(self.GROUP)["message_ids"], [5, 77])
        run(typed.group_reply, text_update("and a gradient?", chat_type="supergroup", reply_to=77))
        self.assertEqual(self.provider.call_count, 2)

    # ---------------------------------------------------------------- Solve

    def solve(self, equation):
        self.type(equation)
        return self.last_reply()

    def test_solve_results(self):
        self.press(f"d1:{STUDENT}:solve")
        self.assertIn("x^2 - 5x + 6 = 0", self.shown())
        text, markup = self.solve("2x + 5 = 17")
        self.assertIn("✅ Solution:\nx = 6", text)
        self.assertIn("Type another equation", text)
        self.assertIn("🧑‍🏫 Explain step by step", self.routes(markup))
        text, _ = self.solve("x^2 - 5x + 6 = 0")
        self.assertIn("Δ = b^2 - 4ac = 1", text)
        self.assertIn("✅ Solutions:\nx = 2, x = 3", text)
        self.assertIn("No real solutions", self.solve("x^2 + 1 = 0")[0])
        self.assertIn("3*4+2 = 14", self.solve("3*4+2")[0])
        self.assertIn("true for every x", self.solve("x = x")[0])
        text, markup = self.solve("x^3 = 8")
        self.assertIn("only solve linear and quadratic", text)
        self.assertIn("🧑‍🏫 Explain step by step", self.routes(markup))

    def test_badly_written_equations_get_an_example_and_no_explain_button(self):
        self.press(f"d1:{STUDENT}:solve")
        for equation, expected in (("hello", "couldn't read"), ("x = 1 = 2", "single = sign"), ("2x + 1", "with an = sign")):
            text, markup = self.solve(equation)
            self.assertIn(expected, text)
            routes = self.routes(markup)
            self.assertNotIn("🧑‍🏫 Explain step by step", routes)
            self.assertEqual(routes["🧮 2x + 5 = 17"], "solve:e:0")

    def test_explain_asks_the_tutor_once(self):
        self.press(f"d1:{STUDENT}:solve")
        _, markup = self.solve("x^2 - 5x + 6 = 0")
        route = self.routes(markup)["🧑‍🏫 Explain step by step"]
        self.press(f"d1:{STUDENT}:{route}")
        prompt = self.provider.call_args.args[0][-1]["content"]
        self.assertIn("x^2 - 5x + 6 = 0", prompt)
        self.assertIn("Solutions: x = 2, x = 3", prompt)
        self.edit_markup.assert_called_once()  # the Explain button is gone
        sent = self.send_message.call_args
        self.assertTrue(sent.args[1].startswith("Step 1: think."))
        self.press(f"d1:{STUDENT}:{route}")
        self.assertEqual(self.provider.call_count, 1)
        self.assertIn("expired", self.answer.call_args.args[0])

    def test_two_quick_taps_on_explain_ask_the_tutor_once(self):
        self.press(f"d1:{STUDENT}:solve")
        _, markup = self.solve("2x + 5 = 17")
        route = self.routes(markup)["🧑‍🏫 Explain step by step"]
        # Both taps read the stored state before either of them takes the result out.
        snapshot = json.dumps(self.mode())
        with patch.object(tools, "current_mode", AsyncMock(side_effect=lambda *args: json.loads(snapshot))):
            self.press(f"d1:{STUDENT}:{route}")
            self.press(f"d1:{STUDENT}:{route}")
        self.assertEqual(self.provider.call_count, 1)
        self.assertEqual(sum(ai._USAGE_FALLBACK.values()), 1, "one daily tutor message used")
        self.assertIn("expired", self.answer.call_args.args[0])

    def test_an_equation_solved_during_an_explanation_keeps_its_explain_button(self):
        self.press(f"d1:{STUDENT}:solve")
        _, markup = self.solve("2x + 5 = 17")
        route = self.routes(markup)["🧑‍🏫 Explain step by step"]
        state_id = self.mode()["id"]

        async def slow_tutor(*args, **kwargs):
            # While the tutor writes, the student solves another equation.
            newer = {"id": "feedbeef", "equation": "3x = 9", "report": "x = 3"}
            input_mode.change_input_mode(STUDENT, STUDENT, state_id, {"last": newer}, 81)
            return "explanation"

        self.provider.side_effect = slow_tutor
        self.press(f"d1:{STUDENT}:{route}")
        self.assertEqual(self.mode()["last"]["id"], "feedbeef")
        self.assertEqual(self.mode()["message_ids"][-2:], [81, 78])

    def test_tutor_is_told_to_write_plain_text(self):
        self.press(f"d1:{STUDENT}:tutor")
        self.type("what is a square root?")
        system = self.provider.call_args.args[0][0]["content"]
        for rule in ("No Markdown", "No LaTeX", "\\frac", "x²", "√"):
            self.assertIn(rule, system)
        self.assertIn("No LaTeX", ai.GENERAL_TUTOR_PROMPT)

    def test_examples_are_copyable_code_and_one_tap_buttons(self):
        self.press(f"d1:{STUDENT}:solve")
        self.assertEqual(code_texts(self.edit_text.call_args), ["2x + 5 = 17", "x^2 - 5x + 6 = 0"])
        routes = self.routes(self.markup(self.edit_text.call_args))
        self.assertEqual(routes["🧮 2x + 5 = 17"], "solve:e:0")
        self.assertEqual(routes["🧮 x² − 5x + 6 = 0"], "solve:e:1")
        self.press(f"d1:{STUDENT}:plot")
        self.assertEqual(code_texts(self.edit_text.call_args), ["y = x^2 - 4x + 3", "sin(x)", "y = x^2 range -5 5"])
        routes = self.routes(self.markup(self.edit_text.call_args))
        self.assertEqual(routes["📈 y = x² − 4x + 3"], "plot:e:0")
        self.assertEqual(routes["📈 sin(x)"], "plot:e:1")

    def test_persian_examples_copy_without_the_direction_mark(self):
        student.set_language(STUDENT, "fa")
        self.press(f"d1:{STUDENT}:solve")
        self.assertIn("\u200e2x + 5 = 17", self.shown())
        self.assertEqual(code_texts(self.edit_text.call_args), ["2x + 5 = 17", "x^2 - 5x + 6 = 0"])

    def test_example_buttons_run_the_example(self):
        self.press(f"d1:{STUDENT}:solve")
        self.press(f"d1:{STUDENT}:solve:e:1")
        self.assertIn("x = 2, x = 3", self.send_message.call_args.args[1])
        self.assertIn("🧑‍🏫 Explain step by step", self.routes(self.markup(self.send_message.call_args)))
        # Also after leaving the tool: the button opens it again.
        self.press(f"d1:{STUDENT}:home")
        self.press(f"d1:{STUDENT}:plot:e:1")
        self.assertIn("y = sin(x)", self.send_photo.call_args.kwargs["caption"])
        self.assertEqual(self.mode()["mode"], "plot")
        self.assertEqual(self.mode()["message_ids"], [5, 80])
        self.press(f"d1:{STUDENT}:plot:e:9")
        self.assertIn("expired", self.answer.call_args.args[0])

    def test_pasting_several_lines_asks_for_one_per_message(self):
        self.press(f"d1:{STUDENT}:plot")
        self.type(self.shown())  # the whole example message, pasted back
        text, markup = self.last_reply()
        self.assertTrue(text.startswith("✏️ Send one function per message"))
        self.assertEqual(code_texts(self.reply_text.call_args), ["y = x^2 - 4x + 3", "sin(x)"])
        self.assertIn("📈 sin(x)", self.routes(markup))
        self.reply_photo.assert_not_called()
        self.press(f"d1:{STUDENT}:solve")
        self.type("2x + 5 = 17\nx^2 - 5x + 6 = 0")
        self.assertTrue(self.last_reply()[0].startswith("✏️ Send one equation per message"))
        self.type("2x + 5 = 17\n")  # a trailing new line is still one equation
        self.assertIn("x = 6", self.last_reply()[0])

    def test_a_formula_copied_from_a_persian_message_works(self):
        self.press(f"d1:{STUDENT}:plot")
        self.type("\u200ey = x^2 - 4x + 3")
        self.assertIn("y = x^2 - 4x + 3", self.reply_photo.call_args.kwargs["caption"])
        self.press(f"d1:{STUDENT}:solve")
        self.type("\u200e2x + 5 = 17")
        self.assertIn("x = 6", self.last_reply()[0])

    def test_persian_solve(self):
        student.set_language(STUDENT, "fa")
        self.press(f"d1:{STUDENT}:solve")
        text, _ = self.solve("x^2 - 5x + 6 = 0")
        self.assertIn("دلتا:\n\u200eΔ = b^2 - 4ac = 1", text)
        self.assertIn("✅ جواب‌ها:\n\u200ex = 2, x = 3", text)

    # ---------------------------------------------------------------- Plot

    def test_plot_sends_a_graph(self):
        self.press(f"d1:{STUDENT}:plot")
        self.assertIn("range -5 5", self.shown())
        self.type("y = x^2 range -3 3")
        call = self.reply_photo.call_args
        self.assertIn("y = x^2", call.kwargs["caption"])
        self.assertIn("Type another function", call.kwargs["caption"])
        self.assertEqual(self.mode()["message_ids"], [5, 79])
        self.type("y = hello(")
        self.assertIn("couldn't draw that", self.last_reply()[0])
        self.assertEqual(self.reply_photo.call_count, 1)

    def test_menu_on_a_graph_sends_a_new_message(self):
        self.press(f"d1:{STUDENT}:home", photo=True)
        self.assertIn("DarsAI 🎓 · Grades 10–11", self.send_message.call_args.args[1])

    # ---------------------------------------------------------------- My progress

    def test_progress_before_practising(self):
        self.press(f"d1:{STUDENT}:prog")
        self.assertIn("haven't practised yet", self.shown())
        self.assertEqual(self.routes(self.markup(self.edit_text.call_args))["✍️ Practice"], "prac")

    def test_progress_lists_every_level_and_suggests_the_weakest_topic(self):
        record_answer(STUDENT, "high_school", "algebra", "hard", "first_try")
        record_answer(STUDENT, "high_school", "algebra", "hard", "missed")
        record_answer(STUDENT, "university", "calculus", "easy", "first_try")
        self.press(f"d1:{STUDENT}:prog")
        text = self.shown()
        self.assertIn("🎓 Grades 10–11", text)
        self.assertIn("Equations with brackets: ▰▰▰▱▱▱▱▱▱▱ 26%\n✅ 1 · ❌ 1", text)
        self.assertIn("Quadratic equations: not started yet", text)
        self.assertIn("🎓 University\nDerivatives:", text)
        self.assertNotIn("Grades 7–9", text)
        self.assertIn("Suggested next: Quadratic equations", text)
        routes = self.routes(self.markup(self.edit_text.call_args))
        self.assertEqual(routes["✍️ Practice: Quadratic equations"], "prac:n:quadratics")


class ReleaseOneLeftoverTests(TelegramMocks):
    """Old buttons, unknown buttons, forum topics, anonymous senders, the group greeting and errors."""

    def press_old(self, data, **kwargs):
        run(router.old_button, button_update(data, **kwargs))

    def test_old_buttons_open_the_new_screens(self):
        expected = {
            "menu:math": "📐 Math · Grades 10–11\n📊 Mastery",
            "main:level": "Choose your level",
            "main:practice": "✍️ Math · Grades 10–11\nPick a topic:",
            "math_action:practice": "✍️ Math · Grades 10–11\nPick a topic:",
            "main:plot": "Type a function",
            "math_action:plot": "Type a function",
            "main:ai": "Type any math question",
            "math_action:tutor": "Type any math question",
            "main:progress": "haven't practised yet",
            "math_action:progress": "haven't practised yet",
            "main:subscribe": "Premium isn't ready yet",
        }
        self.assertEqual(set(expected), set(router.OLD_BUTTONS))
        for data, text in expected.items():
            with self.subTest(data=data):
                self.press_old(data)
                self.assertIn(text, self.edit_text.call_args.args[0])

    def test_old_level_button_saves_the_level(self):
        self.press_old("math_level:university")
        self.assertEqual(get_user_level(STUDENT, STUDENT), "university")
        self.assertIn("Level: University", self.edit_text.call_args.args[0])
        self.assertIn("Saved", self.answer.call_args.args[0])

    def test_old_buttons_belong_to_whoever_presses_them(self):
        self.press_old("main:practice", user_id=7, chat_type="supergroup")
        buttons = self.buttons(self.markup(self.edit_text.call_args))
        self.assertTrue(all(b.callback_data.startswith("d1:7:") for b in buttons))

    def test_every_button_reaches_the_right_handler(self):
        def first_handler(data):
            update = button_update(data)
            return next(h.callback for h in main.telegram_app.handlers[0]
                        if isinstance(h, CallbackQueryHandler) and h.check_update(update))
        for data in list(router.OLD_BUTTONS) + ["math_level:high_school"]:
            self.assertIs(first_handler(data), router.old_button, data)
        self.assertIs(first_handler(f"d1:{STUDENT}:home"), router.callback_router)
        self.assertIs(first_handler("ai:newchat"), main.ai_callback_handler)
        for data in ("zzz", "math_unknown:1", "something:else"):
            self.assertIs(first_handler(data), router.unknown_button, data)

    def test_unknown_buttons_are_answered(self):
        run(router.unknown_button, button_update("zzz:1"))
        self.assertIn("old version", self.answer.call_args.args[0])
        run(router.callback_router, button_update("d1:not-a-user:home"))
        self.assertIn("old version", self.answer.call_args.args[0])
        self.edit_text.assert_not_called()

    def test_math_and_mathhelp_show_the_new_menu(self):
        self.existing_student()
        run(math_commands.math_command, text_update("/math"))
        welcome, menu = self.reply_text.call_args_list
        self.assertTrue(all(b.callback_data.startswith(f"d1:{STUDENT}:") for b in self.buttons(self.markup(menu))))
        run(math_commands.mathhelp_command, text_update("/mathhelp"))
        self.assertTrue(all(b.callback_data.startswith(f"d1:{STUDENT}:") for b in self.buttons(self.markup(self.reply_text.call_args))))

    def test_help_shows_the_commands_with_the_home_buttons(self):
        run(main.help_command, text_update("/help"))
        call = self.reply_text.call_args
        self.assertIn("DarsAI help", call.args[0])
        self.assertTrue(all(b.callback_data.startswith(f"d1:{STUDENT}:") for b in self.buttons(self.markup(call))))

    def test_every_command_runs_without_an_error(self):
        """Each command, typed with no arguments and with arguments, in a private chat and in a group."""
        commands = {}
        for handlers in main.telegram_app.handlers.values():
            for handler in handlers:
                if isinstance(handler, CommandHandler):
                    for command in handler.commands:
                        commands[command] = handler.callback
        self.assertIn("help", commands)
        self.assertIn("start", commands)
        with patch.object(ai, "call_ai_provider", AsyncMock(return_value="An answer.")):
            for command, callback in sorted(commands.items()):
                for chat_type in ("private", "supergroup"):
                    for args in ([], ["high_school", "algebra", "2x", "+", "1", "=", "5"]):
                        with self.subTest(command=command, chat_type=chat_type, args=args):
                            text = " ".join([f"/{command}"] + args)
                            run(callback, text_update(text, chat_type=chat_type), args=args)

    def test_messages_after_a_button_stay_in_the_forum_topic(self):
        run(router.callback_router, button_update(f"d1:{STUDENT}:home", chat_type="supergroup", photo=True, topic=12))
        self.assertEqual(self.send_message.call_args.kwargs["message_thread_id"], 12)
        run(router.callback_router, button_update(f"d1:{STUDENT}:home", chat_type="supergroup", photo=True))
        self.assertIsNone(self.send_message.call_args.kwargs["message_thread_id"])

    def anonymous_update(self, text="/start", automatic_forward=False):
        message = {
            "message_id": 3, "date": DATE, "chat": _chat("supergroup", STUDENT), "text": text,
            "from": {"id": 1087968824, "is_bot": True, "first_name": "Group", "username": "GroupAnonymousBot"},
            "sender_chat": {"id": -1001, "type": "supergroup", "title": "Class"},
            "entities": [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}] if text.startswith("/") else [],
        }
        if automatic_forward:
            message["is_automatic_forward"] = True
        return Update.de_json({"update_id": 4, "message": message}, BOT)

    def test_anonymous_admins_are_asked_to_post_as_themselves(self):
        handler = next(h for h in main.telegram_app.handlers[-1] if h.callback is groups.anonymous_sender)
        self.assertTrue(handler.check_update(self.anonymous_update()))
        self.assertFalse(handler.check_update(self.anonymous_update(automatic_forward=True)))
        self.assertFalse(handler.check_update(text_update("/start", chat_type="supergroup")))
        with self.assertRaises(ApplicationHandlerStop):
            run(groups.anonymous_sender, self.anonymous_update())
        text = self.reply_text.call_args.args[0]
        self.assertIn("Remain anonymous", text)
        self.assertIn("ناشناس ماندن", text)

    def membership_update(self, old_status, new_status, language_code="fa"):
        bot = {"id": 1, "is_bot": True, "first_name": "DarsAI"}
        return Update.de_json({"update_id": 5, "my_chat_member": {
            "chat": {"id": -1001, "type": "supergroup", "title": "Class"},
            "from": _user(STUDENT, language_code), "date": DATE,
            "old_chat_member": {"user": bot, "status": old_status},
            "new_chat_member": {"user": bot, "status": new_status},
        }}, BOT)

    def test_greeting_when_added_to_a_group(self):
        run(groups.bot_added, self.membership_update("left", "member"))
        chat_id, text = self.send_message.call_args.args
        self.assertEqual(chat_id, -1001)
        self.assertIn("\u200e/start", text)
        self.assertIn("ریپلای", text)
        self.send_message.reset_mock()
        run(groups.bot_added, self.membership_update("member", "left"))
        self.send_message.assert_not_called()

    def test_errors_are_shown_in_the_student_language(self):
        context = SimpleNamespace(bot=BOT, error=RuntimeError("database is down"))
        with self.assertLogs("darsai", "ERROR"):
            asyncio.run(main.error_handler(text_update("hi", language_code="fa"), context))
        text = self.reply_text.call_args.args[0]
        self.assertIn("مشکلی پیش اومد", text)
        self.assertNotIn("database", text)


def shared_topics():
    from modules.math.topics import TOPIC_LEVEL
    return list(TOPIC_LEVEL)


class CommandMenuTests(unittest.TestCase):
    def test_start_help_and_privacy(self):
        with patch.object(ExtBot, "set_my_commands", AsyncMock()) as set_commands:
            asyncio.run(main.setup_bot_commands())
        self.assertEqual(set_commands.call_count, 2)
        for call in set_commands.call_args_list:
            # /privacy must be in the menu: Telegram's "Privacy Policy" in the bot's profile opens it only then.
            self.assertEqual([c.command for c in call.args[0]], ["start", "help", "privacy"])
        persian = next(c for c in set_commands.call_args_list if c.kwargs["language_code"] == "fa")
        self.assertTrue(re.search("[؀-ۿ]", persian.args[0][0].description))

    def setup_descriptions(self, current=lambda lang: "old text", error=None):
        """Run setup_bot_descriptions with Telegram mocked. Returns the two set_* mocks."""
        def lang(language_code):
            return language_code or "en"
        get_long = AsyncMock(side_effect=lambda language_code=None: BotDescription(current(lang(language_code))))
        get_short = AsyncMock(side_effect=lambda language_code=None: BotShortDescription(current(lang(language_code))))
        set_long, set_short = AsyncMock(side_effect=error), AsyncMock()
        with patch.object(ExtBot, "get_my_description", get_long), patch.object(ExtBot, "get_my_short_description", get_short), \
                patch.object(ExtBot, "set_my_description", set_long), patch.object(ExtBot, "set_my_short_description", set_short):
            asyncio.run(main.setup_bot_descriptions())
        return set_long, set_short

    def test_descriptions_in_english_and_persian(self):
        set_long, set_short = self.setup_descriptions()
        self.assertEqual([c.kwargs["language_code"] for c in set_long.call_args_list], [None, "fa"])
        self.assertEqual([c.kwargs["language_code"] for c in set_short.call_args_list], [None, "fa"])
        english, persian = (c.args[0] for c in set_long.call_args_list)
        self.assertTrue(english.startswith("Hi! I'm DarsAI, your math study buddy 🎓\n✍️ Practice"))
        self.assertTrue(english.endswith("From middle school to university. Tap Start!"))
        self.assertTrue(persian.startswith("سلام! من DarsAI هستم، دستیار ریاضیت 🎓"))
        self.assertEqual(set_short.call_args_list[0].args[0][:14], "Math practice ")
        self.assertIn("رایگان، به فارسی و انگلیسی", set_short.call_args_list[1].args[0])
        for call in set_long.call_args_list:
            self.assertLessEqual(len(call.args[0]), 512)  # Telegram's limits
        for call in set_short.call_args_list:
            self.assertLessEqual(len(call.args[0]), 120)

    def test_descriptions_already_set_are_left_alone(self):
        texts ={(lang, key): t(lang, key, bot="DarsAI") for lang in ("en", "fa") for key in ("bot.description", "bot.short_description")}
        set_long, set_short = self.setup_descriptions(
            current=lambda lang: texts[(lang, "bot.description")])
        set_long.assert_not_called()
        self.assertEqual(set_short.call_count, 2, "the short text differs from the long one")
        set_long, set_short = self.setup_descriptions(
            current=lambda lang: texts[(lang, "bot.short_description")])
        set_short.assert_not_called()

    def test_a_description_failure_does_not_stop_the_bot(self):
        with self.assertLogs("darsai", "WARNING"):
            self.setup_descriptions(error=TimedOut())
