import asyncio
import re
import string
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup, Update
from telegram.ext import ExtBot

import main
from modules import ai, student
from modules.i18n import RTL_LANGUAGES, STRINGS, detect_language, local_digits, t
from modules.math import math as math_commands
from modules.math import shared
from modules.math.shared import get_mastery, get_user_level, next_mastery, record_answer
from modules.ui import core, home, practice, router

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


def button_update(data: str, user_id: int = STUDENT, chat_type: str = "private", language_code: str = "en", photo: bool = False) -> Update:
    owner_chat = _chat(chat_type, STUDENT)
    message = {"message_id": 5, "date": DATE, "chat": owner_chat, "from": BOT_USER}
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
        shared.MASTERY_FALLBACK.clear()
        shared.ACTIVE_QUESTION_FALLBACK.clear()
        # Sent messages get ids 77 (replies) and 78 (new messages). Edited ones keep 5.
        self.reply_text = self._patch(Message, "reply_text", SimpleNamespace(message_id=77))
        self.answer = self._patch(CallbackQuery, "answer")
        self.edit_text = self._patch(CallbackQuery, "edit_message_text")
        self.edit_markup = self._patch(CallbackQuery, "edit_message_reply_markup")
        self.send_message = self._patch(ExtBot, "send_message", SimpleNamespace(message_id=78))
        self.bot_edit_markup = self._patch(ExtBot, "edit_message_reply_markup")

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
        self.press(f"d1:{STUDENT}:learn")
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


class PracticeTests(TelegramMocks):
    GROUP = -1001

    def press(self, data, **kwargs):
        run(router.callback_router, button_update(data, **kwargs))

    def type(self, text, **kwargs):
        run(home.text_message, text_update(text, **kwargs))

    def question(self, chat_id=STUDENT):
        return shared.ACTIVE_QUESTION_FALLBACK.get((chat_id, STUDENT))

    def wrong_answer(self, question):
        return "1000" if question["answer"].count(",") == 0 else "1000, 2000"

    def last_reply(self):
        call = self.reply_text.call_args
        return call.args[0], self.markup(call)

    def routes(self, markup):
        return {b.text: b.callback_data.split(":", 2)[2] for b in self.buttons(markup)}

    def test_practice_lists_the_topics_of_the_level(self):
        record_answer(STUDENT, "high_school", "algebra", "easy", "first_try")
        self.press(f"d1:{STUDENT}:prac")
        text = self.edit_text.call_args.args[0]
        self.assertIn("Practice · High School", text)
        self.assertIn("Equations with brackets: ▰▰▱▱▱▱▱▱▱▱ 18%", text)
        self.assertIn("Quadratic equations: not started yet", text)
        routes = self.routes(self.markup(self.edit_text.call_args))
        self.assertEqual(routes["Equations with brackets"], "prac:n:algebra")
        self.assertEqual(routes["🏠 Menu"], "home")

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
        self.assertIn("What would you like to do?", self.last_reply()[0])
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
        handler = next(h for h in main.telegram_app.handlers[0] if getattr(h, "callback", None) is practice.group_reply)
        self.assertTrue(handler.check_update(reply))
        self.assertFalse(handler.check_update(text_update(q["answer"], chat_type="supergroup")))

        # A reply to another message, or by someone else, is not an answer.
        run(practice.group_reply, text_update(q["answer"], chat_type="supergroup", reply_to=99))
        run(practice.group_reply, text_update(q["answer"], chat_type="supergroup", user_id=7, reply_to=5))
        self.reply_text.assert_not_called()

        run(practice.group_reply, reply)
        self.assertTrue(self.last_reply()[0].startswith("✅ Correct!"))

    def test_group_retry_message_also_takes_replies(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra", chat_type="supergroup")
        q = self.question(self.GROUP)
        run(practice.group_reply, text_update(self.wrong_answer(q), chat_type="supergroup", reply_to=5))
        self.assertIn("Reply to this message with your new answer", self.last_reply()[0])
        self.assertEqual(self.question(self.GROUP)["message_ids"], [5, 77])
        run(practice.group_reply, text_update(q["answer"], chat_type="supergroup", reply_to=77))
        self.assertTrue(self.last_reply()[0].startswith("✅ Correct on the second try!"))

    def test_mastery_follows_the_student_into_other_chats(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra", chat_type="supergroup")
        run(practice.group_reply, text_update(self.question(self.GROUP)["answer"], chat_type="supergroup", reply_to=5))
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
        core.pack(big, "prac", "n", "linear_equations", "a")
        core.pack(big, "prac", "s", "0123abcd")


class CommandMenuTests(unittest.TestCase):
    def test_only_start_and_help(self):
        with patch.object(ExtBot, "set_my_commands", AsyncMock()) as set_commands:
            asyncio.run(main.setup_bot_commands())
        self.assertEqual(set_commands.call_count, 2)
        for call in set_commands.call_args_list:
            self.assertEqual([c.command for c in call.args[0]], ["start", "help"])
        persian = next(c for c in set_commands.call_args_list if c.kwargs["language_code"] == "fa")
        self.assertTrue(re.search("[؀-ۿ]", persian.args[0][0].description))
