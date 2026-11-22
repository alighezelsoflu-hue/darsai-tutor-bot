"""Course home: the course list, home, the Math hub, 🔜 screens with Notify me, ▶️ Continue, setup and the
one-time bottom keyboard notice."""

import asyncio
from datetime import date
from unittest.mock import patch

from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import TypeHandler

import main
from modules import courses, notify, stats, student
from modules.i18n import STRINGS, UI_LANGUAGES, t
from modules.math import shared
from modules.math.prompts import math_tutor_prompt
from modules.math.shared import get_user_level, record_answer
from modules.ui import courses as courses_ui
from modules.ui import groups, home, router, setup, typed
from tests.test_ui import STUDENT, TelegramMocks, button_update, math_routes, run, text_update


def labels(markup):
    return [[b.text for b in row] for row in markup.inline_keyboard]


class CourseListTests(TelegramMocks):
    def test_every_course_is_complete(self):
        for course in courses.COURSES.values():
            with self.subTest(course=course.id):
                self.assertEqual(set(course.names), set(UI_LANGUAGES))
                self.assertIn(course.kind, (courses.SUBJECT, courses.PATH, courses.EXAM))
                self.assertTrue(course.tutor and course.rules)
                if course.live:
                    self.assertTrue(course.hub)
                    self.assertTrue(set(course.hub) <= {"next"} | set(courses_ui.HUB_BUTTONS))
                else:
                    for lang in UI_LANGUAGES:
                        self.assertIn(f"soon.{course.id}", STRINGS[lang])
        self.assertEqual([c for c in courses.COURSES if courses.COURSES[c].live], ["math"])
        self.assertEqual(courses.EXAMS, ("konkur",))

    def test_math_tutor_prompt_is_unchanged(self):
        prompt = math_tutor_prompt("high_school", "quadratics", "English")
        self.assertTrue(prompt.startswith(
            "You are DarsAI, a specialized math tutor for students.\nStudent level: High School.\nTopic: quadratics.\n"
            "Respond in English.\n\nTeaching rules:\n1. Do not just give the final answer. Teach step by step.\n"
        ))
        self.assertIn("\n7. If a deterministic result is provided, do not change it; explain it.\n8. Write plain text only.", prompt)
        self.assertNotIn("\n9.", prompt)
        self.assertIn("\n9. Write every formula on its own line", math_tutor_prompt("high_school", "math", "Persian/Farsi"))

    def test_biology_replaced_astrology(self):
        self.assertNotIn("astrology", courses.COURSES)
        biology = courses.COURSES["biology"]
        self.assertEqual((biology.emoji, biology.names, biology.kind, biology.live), ("🧬", {"en": "Biology", "fa": "زیست\u200cشناسی"}, courses.SUBJECT, False))
        prompt = courses.tutor_prompt("biology", "high_school", "cells", "English")
        self.assertIn("You are DarsAI, a specialized biology tutor for students.", prompt)
        self.assertIn("Connect structure to function.", prompt)
        for lang in UI_LANGUAGES:
            self.assertNotIn("soon.astrology", STRINGS[lang])
        # School subjects first, then the path courses.
        self.assertEqual(courses.GRID, ("math", "physics", "chemistry", "biology", "ai", "astronomy"))


class ScreenTests(TelegramMocks):
    def press(self, data, **kwargs):
        run(router.callback_router, button_update(data, **kwargs))

    def shown(self):
        call = self.edit_text.call_args
        return call.args[0], self.markup(call)


class HomeTests(ScreenTests):
    def test_home_is_the_course_picker(self):
        self.press(f"d1:{STUDENT}:home")
        text, markup = self.shown()
        self.assertEqual(text, "DarsAI 🎓 · Grades 10–11\n\nChoose a course to start:")
        self.assertEqual(labels(markup), [
            ["▶️ Start: Equations with brackets"],
            ["📐 Math", "⚛️ Physics 🔜"],
            ["🧪 Chemistry 🔜", "🧬 Biology 🔜"],
            ["🤖 AI course 🔜", "🔭 Astronomy 🔜"],
            ["🎯 Konkur 🔜"],
            ["📊 Progress", "💎 Premium", "⚙️ Settings"],
        ])
        routes = math_routes(self.buttons(markup))
        self.assertEqual(routes["▶️ Start: Equations with brackets"], "cont")
        self.assertEqual(routes["📐 Math"], "c:math")
        self.assertEqual(routes["🧬 Biology 🔜"], "c:biology")
        self.assertEqual(routes["🎯 Konkur 🔜"], "c:konkur")

    def test_persian_home(self):
        student.set_language(STUDENT, "fa")
        student.set_level(STUDENT, "middle_school")
        self.press(f"d1:{STUDENT}:home")
        text, markup = self.shown()
        self.assertEqual(text, "منوی اصلی DarsAI 🎓 · متوسطه اول (هفتم تا نهم)\n\nیه درس انتخاب کن تا شروع کنیم:")
        rows = labels(markup)
        self.assertEqual(rows[0], ["▶️ شروع: معادله‌ی درجه اول"])
        # Mirrored: the first of each row sits on the right.
        self.assertEqual(rows[1], ["⚛️ فیزیک 🔜", "📐 ریاضی"])
        self.assertEqual(rows[2], ["🧬 زیست‌شناسی 🔜", "🧪 شیمی 🔜"])
        self.assertEqual(rows[4], ["🎯 کنکور 🔜"])

    def test_after_practising_home_offers_to_continue(self):
        record_answer(STUDENT, "high_school", "quadratics", "easy", "first_try")
        self.press(f"d1:{STUDENT}:home")
        text, markup = self.shown()
        self.assertEqual(text, "DarsAI 🎓 · Grades 10–11\n\nPick up where you left off, or choose a course:")
        self.assertEqual(labels(markup)[0], ["▶️ Continue: Quadratic equations"])

    def test_group_home_names_the_owner(self):
        self.press(f"d1:{STUDENT}:home", chat_type="supergroup")
        self.assertTrue(self.shown()[0].startswith("👤 Sara\n\nDarsAI 🎓 · Grades 10–11"))


class MathHubTests(ScreenTests):
    def test_hub_text_and_buttons(self):
        record_answer(STUDENT, "high_school", "algebra", "hard", "first_try")
        self.press(f"d1:{STUDENT}:c:math")
        text, markup = self.shown()
        # Mastery is the average of the level's topics (algebra 30%, quadratics not started).
        self.assertEqual(text, "📐 Math · Grades 10–11\n📊 Mastery ▰▰▱▱▱▱▱▱▱▱ 15%\n⭐ Suggested next: Quadratic equations (🟢 Easy)")
        self.assertEqual(labels(markup), [
            ["▶️ Practice: Quadratic equations"],
            ["📘 Learn", "✍️ Practice"],
            ["🎯 Konkur Math 🔜", "🧑‍🏫 Ask the tutor"],
            ["🧮 Solve", "📈 Plot"],
            ["🏠 Menu"],
        ])
        routes = math_routes(self.buttons(markup))
        self.assertEqual(routes, {
            "▶️ Practice: Quadratic equations": "prac:n:quadratics",
            "📘 Learn": "learn", "✍️ Practice": "prac",
            "🎯 Konkur Math 🔜": "konkur", "🧑‍🏫 Ask the tutor": "tutor",
            "🧮 Solve": "solve", "📈 Plot": "plot", "🏠 Menu": "home",
        })
        # Every Math route carries the course.
        self.assertTrue(all(b.callback_data.startswith(f"d1:{STUDENT}:c:math") for b in self.buttons(markup)[:-1]))

    def test_persian_hub(self):
        student.set_language(STUDENT, "fa")
        self.press(f"d1:{STUDENT}:c:math")
        text, markup = self.shown()
        self.assertEqual(text, "📐 ریاضی · دهم و یازدهم\n📊 تسلط ▱▱▱▱▱▱▱▱▱▱ ۰٪\n⭐ پیشنهاد بعدی: معادله‌ی پرانتزدار (🟢 آسان)")
        self.assertEqual(labels(markup)[2], ["🧑‍🏫 از معلم بپرس", "🎯 کنکور ریاضی 🔜"])

    def test_every_hub_button_opens_its_screen(self):
        expected = {
            "learn": "📘 Math · Grades 10–11\nPick a topic:",
            "prac": "✍️ Math · Grades 10–11\nPick a topic:",
            "tutor": "🧑‍🏫 Ask the tutor · Math · Grades 10–11\n",
            "solve": "🧮 Solve · Math\nType an equation",
            "plot": "📈 Plot · Math\nType a function",
            "konkur": "🎯 Konkur is coming soon\n",
            "prac:n:quadratics": "✍️ Math › Quadratic equations · 🟢 Easy",
        }
        for route, start in expected.items():
            with self.subTest(route=route):
                self.press(f"d1:{STUDENT}:c:math:{route}")
                self.assertTrue(self.shown()[0].startswith(start), self.shown()[0])

    def test_back_to_math_leaves_the_tool(self):
        self.press(f"d1:{STUDENT}:c:math:solve")
        self.assertIsNotNone(shared_input_mode())
        self.press(f"d1:{STUDENT}:c:math")
        self.assertIsNone(shared_input_mode())

    def test_old_routes_still_open_the_math_screens(self):
        self.press(f"d1:{STUDENT}:prac:n:algebra")
        self.assertIn("✍️ Math › Equations with brackets", self.shown()[0])
        self.press(f"d1:{STUDENT}:learn:quadratics")
        self.assertTrue(self.shown()[0].startswith("📘 Math · Grades 10–11 › Quadratic equations"))

    def test_unknown_course_or_screen(self):
        self.press(f"d1:{STUDENT}:c:music")
        self.edit_text.assert_not_called()
        self.assertIn("expired", self.answer.call_args.args[0])
        self.press(f"d1:{STUDENT}:c:math:zzz")
        self.assertTrue(self.shown()[0].startswith("📐 Math"))


def shared_input_mode():
    from modules import input_mode
    return input_mode.get_input_mode(STUDENT, STUDENT)


class ComingSoonTests(ScreenTests):
    def test_notify_me_is_saved_per_student_and_course(self):
        self.press(f"d1:{STUDENT}:c:physics")
        text, markup = self.shown()
        self.assertEqual(text, t("en", "soon.physics") + "\n\nWant to know when it's ready?")
        self.assertEqual(math_routes(self.buttons(markup)), {"🔔 Notify me": "c:physics:n", "🏠 Menu": "home"})
        self.press(f"d1:{STUDENT}:c:physics:n")
        self.assertEqual(self.answer.call_args.args[0], "🔔 Saved. I'll tell you when it's ready.")
        text, markup = self.shown()
        self.assertTrue(text.endswith("\n\n✅ I'll tell you when it's ready."))
        self.assertEqual(labels(markup), [["🏠 Menu"]])
        self.assertTrue(notify.wants_notice(STUDENT, "physics"))
        self.assertFalse(notify.wants_notice(STUDENT, "chemistry"))
        self.assertEqual(notify._FALLBACK[(STUDENT, "physics")]["language"], "en")
        # Opening it again remembers, and a second tap saves nothing new.
        self.press(f"d1:{STUDENT}:c:physics")
        self.assertTrue(self.shown()[0].endswith("✅ I'll tell you when it's ready."))
        self.press(f"d1:{STUDENT}:c:physics:n")
        self.assertEqual(notify.notice_summary()["courses"]["physics"], 1)

    def test_konkur_math_has_back_to_math(self):
        self.press(f"d1:{STUDENT}:c:math:konkur")
        text, markup = self.shown()
        self.assertTrue(text.startswith("🎯 Konkur is coming soon\nMini mock tests"))
        self.assertEqual(math_routes(self.buttons(markup)), {"🔔 Notify me": "konkur:n", "🔙 Math": "c:math"})
        self.press(f"d1:{STUDENT}:c:math:konkur:n")
        self.assertTrue(notify.wants_notice(STUDENT, "konkur"))
        self.assertEqual(labels(self.shown()[1]), [["🔙 Math"]])

    def test_persian_coming_soon(self):
        student.set_language(STUDENT, "fa")
        for course, start in (
            ("ai", "🤖 دوره‌ی هوش مصنوعی به‌زودی میاد\nچهار مسیر، از نوجوون‌های ۱۲ تا ۱۴ ساله تا دانشجوها:"),
            ("konkur", "🎯 کنکور به‌زودی میاد\nآزمون آزمایشی کوتاه چهارگزینه‌ای"),
            ("biology", "🧬 زیست‌شناسی به‌زودی میاد\nدرس و تمرین برای پایه‌ی خودت، از سلول و ژنتیک"),
        ):
            self.press(f"d1:{STUDENT}:c:{course}")
            text, markup = self.shown()
            self.assertTrue(text.startswith(start), text)
            self.assertTrue(text.endswith("\n\nمی‌خوای وقتی آماده شد خبرت کنم؟"))
        self.assertEqual(labels(markup), [["🔔 خبرم کن"], ["🏠 منو"]])
        self.press(f"d1:{STUDENT}:c:biology:n")
        self.assertEqual(notify._FALLBACK[(STUDENT, "biology")]["language"], "fa")

    def test_astrology_buttons_in_old_messages_have_expired(self):
        for route in ("c:astrology", "c:astrology:n", "su:c:astrology"):
            self.answer.reset_mock()
            self.press(f"d1:{STUDENT}:{route}")
            self.assertIn("expired", self.answer.call_args.args[0], route)
        self.edit_text.assert_not_called()
        with self.assertRaises(ValueError):
            notify.add_notice(STUDENT, "astrology", "en")

    def test_a_live_course_is_not_a_notify_choice(self):
        with self.assertRaises(ValueError):
            notify.add_notice(STUDENT, "math", "en")

    def test_stats_count_each_course_without_admins(self):
        notify.add_notice(1, "physics", "en")
        notify.add_notice(1, "ai", "fa")
        notify.add_notice(2, "physics", "en")
        notify.add_notice(99, "physics", "en")  # an admin
        # Picks for Astrology from before Biology replaced it stay in storage, but aren't counted.
        notify._FALLBACK[(1, "astrology")] = {"language": "en", "created_at": 0}
        notify._FALLBACK[(3, "astrology")] = {"language": "fa", "created_at": 0}
        summary = notify.notice_summary(exclude={99})
        self.assertEqual(summary["students"], 2)
        self.assertEqual(summary["courses"], {"physics": 2, "chemistry": 0, "biology": 0, "ai": 1, "astronomy": 0, "konkur": 0})
        text = stats.format_stats(stats.collect_stats(date(2026, 11, 22), admins={99}))
        self.assertIn(
            "🔔 Notify me (coming-soon courses): 2 students\n⚛️ Physics: 2\n🧪 Chemistry: 0\n🧬 Biology: 0\n"
            "🤖 AI course: 1\n🔭 Astronomy: 0\n🎯 Konkur: 0", text)
        self.assertNotIn("Astrology", text)


class ContinueTests(ScreenTests):
    def type(self, text, **kwargs):
        run(typed.private_text, text_update(text, **kwargs))

    def question(self):
        return shared.ACTIVE_QUESTION_FALLBACK.get((STUDENT, STUDENT))

    def test_continue_reopens_the_unfinished_question(self):
        self.press(f"d1:{STUDENT}:c:math:prac:n:algebra")
        question = self.question()
        self.type("1000")  # a wrong answer: one try left
        self.press(f"d1:{STUDENT}:c:math:solve")
        self.press(f"d1:{STUDENT}:cont")
        text, _ = self.shown()
        self.assertTrue(text.startswith("✍️ Math › Equations with brackets"))
        self.assertIn("Type your new answer", text)
        self.assertEqual(self.question()["id"], question["id"])
        self.assertEqual(self.question()["attempts"], 1)
        self.assertIsNone(shared_input_mode(), "typed text answers the question again")
        self.type(question["answer"])
        self.assertTrue(self.reply_text.call_args.args[0].startswith("✅ Correct on the second try!"))

    def test_the_bottom_continue_button_works_in_both_languages(self):
        self.press(f"d1:{STUDENT}:c:math:prac:n:quadratics")
        for label in ("▶️ Continue", "▶️ ادامه"):
            self.type(label)
            self.assertTrue(self.reply_text.call_args.args[0].startswith("✍️ Math › Quadratic equations"))
        # Each message showing the question takes replies (77 is the mocked reply).
        self.assertEqual(self.question()["message_ids"], [5, 77])

    def test_continue_after_a_finished_question_starts_a_new_one_in_that_topic(self):
        record_answer(STUDENT, "high_school", "algebra", "easy", "first_try")
        record_answer(STUDENT, "university", "calculus", "easy", "first_try")
        self.press(f"d1:{STUDENT}:cont")
        self.assertEqual(self.question()["topic"], "calculus", "the topic practised last, at any level")

    def test_a_new_student_starts_with_the_weakest_topic_of_their_level(self):
        student.set_level(STUDENT, "middle_school")
        self.press(f"d1:{STUDENT}:home")
        self.assertEqual(labels(self.shown()[1])[0], ["▶️ Start: Linear equations"])
        self.press(f"d1:{STUDENT}:cont")
        self.assertEqual(self.question()["topic"], "linear_equations")

    def test_a_question_older_than_a_day_is_not_reopened(self):
        self.press(f"d1:{STUDENT}:c:math:prac:n:quadratics")
        old_id = self.question()["id"]
        shared.ACTIVE_QUESTION_FALLBACK[(STUDENT, STUDENT)]["asked_at"] = 0
        self.press(f"d1:{STUDENT}:cont")
        self.assertNotEqual(self.question()["id"], old_id)
        # Nothing practised yet, so ▶️ Start: the weakest topic of the level.
        self.assertEqual(self.question()["topic"], "algebra")


class SetupTests(TelegramMocks):
    def press(self, data, **kwargs):
        run(router.callback_router, button_update(data, **kwargs))

    def test_new_students_answer_three_questions(self):
        run(home.start_command, text_update("/start", language_code="en"))
        (question,) = self.reply_text.call_args_list
        self.assertEqual(question.args[0], "👋 Welcome to DarsAI 🎓\nNot just answers. Real learning.\n\nFirst, which language do you prefer?")
        self.assertIsInstance(self.markup(question), InlineKeyboardMarkup)
        self.assertEqual(labels(self.markup(question)), [["فارسی", "English"]])
        self.assertEqual(math_routes(self.buttons(self.markup(question)))["فارسی"], "su:l:fa")

        self.press(f"d1:{STUDENT}:su:l:fa")
        self.assertEqual(student.get_student(STUDENT)["language"], "fa")
        text = self.edit_text.call_args.args[0]
        self.assertTrue(text.startswith("قدم ۲ از ۳\n🎓 الان چی می‌خونی؟\n"))
        self.assertEqual(labels(self.markup(self.edit_text.call_args)), [
            ["متوسطه اول (هفتم تا نهم)"], ["دهم و یازدهم"], ["دوازدهم و کنکور"], ["دانشگاه"],
        ])

        self.press(f"d1:{STUDENT}:su:v:pre_college")
        self.assertEqual(get_user_level(STUDENT, STUDENT), "pre_college")
        self.assertEqual(self.edit_text.call_args.args[0], "قدم ۳ از ۳\n📚 با کدوم درس شروع کنیم؟")
        rows = labels(self.markup(self.edit_text.call_args))
        self.assertEqual(rows[0], ["⚛️ فیزیک 🔜", "📐 ریاضی"])
        self.assertEqual(rows[-1], ["🎯 کنکور 🔜"])
        self.assertFalse(student.get_student(STUDENT)["setup_done"])

        self.press(f"d1:{STUDENT}:su:c:math")
        self.assertTrue(student.get_student(STUDENT)["setup_done"])
        self.edit_markup.assert_called_once_with(reply_markup=None)
        done, hub = self.send_message.call_args_list
        self.assertEqual(done.args[1], "✅ همه‌چی آماده‌ست! پایین صفحه، «🏠 منو» صفحه‌ی اصلی رو باز می‌کنه و «▶️ ادامه» تو رو می‌بره همون‌جا که بودی.")
        self.assertIsInstance(self.markup(done), ReplyKeyboardMarkup)
        self.assertEqual([b.text for b in self.markup(done).keyboard[0]], ["▶️ ادامه", "🏠 منو"])
        self.assertTrue(hub.args[1].startswith("📐 ریاضی · دوازدهم و کنکور\n📊 تسلط"))

        # A second tap on the old button: setup is done, so it only opens the course.
        self.send_message.reset_mock()
        self.press(f"d1:{STUDENT}:su:c:math")
        self.send_message.assert_not_called()
        self.assertTrue(self.edit_text.call_args.args[0].startswith("📐 ریاضی"))

        # Afterwards /start is the welcome and home.
        self.reply_text.reset_mock()
        run(home.start_command, text_update("/start"))
        welcome, menu = self.reply_text.call_args_list
        self.assertIn("خوش اومدی", welcome.args[0])

    def test_a_coming_soon_first_course_opens_its_screen(self):
        run(home.start_command, text_update("/start"))
        self.press(f"d1:{STUDENT}:su:l:en")
        self.press(f"d1:{STUDENT}:su:v:university")
        self.press(f"d1:{STUDENT}:su:c:astronomy")
        done, soon = self.send_message.call_args_list
        self.assertTrue(done.args[1].startswith("✅ All set! At the bottom, 🏠 Menu opens the home screen"))
        self.assertTrue(soon.args[1].startswith("🔭 Astronomy is coming soon\n"))
        self.assertIn("🔔 Notify me", [b.text for b in self.buttons(self.markup(soon))])

    def test_persian_telegram_users_get_the_first_question_in_persian(self):
        run(home.start_command, text_update("/start", language_code="fa"))
        question = self.reply_text.call_args
        self.assertTrue(question.args[0].startswith("👋 به DarsAI خوش اومدی 🎓\n"))
        self.assertEqual(labels(self.markup(question)), [["English", "فارسی"]])

    def test_groups_have_no_setup(self):
        run(home.start_command, text_update("/start", chat_type="supergroup"))
        (menu,) = self.reply_text.call_args_list
        self.assertIn("👤 Sara", menu.args[0])
        self.assertIn("DarsAI 🎓 · Grades 10–11", menu.args[0])

    def test_bad_setup_buttons(self):
        for route in ("su", "su:l:de", "su:v:wizard", "su:c:music"):
            self.press(f"d1:{STUDENT}:{route}")
            self.assertIn("expired", self.answer.call_args.args[0])
        self.assertFalse(student.get_student(STUDENT)["setup_done"])


class KeyboardNoticeTests(TelegramMocks):
    def notice(self, update):
        run(setup.keyboard_notice, update)

    def old_student(self, user_id=STUDENT):
        """Set up before the new bottom keyboard (what migration 1 makes of every known student)."""
        student.finish_setup(user_id, 0)

    def notices(self):
        return [call for call in self.send_message.call_args_list if call.args[1] == t("en", "keyboard.notice")]

    def test_existing_students_get_the_new_keyboard_once(self):
        self.old_student()
        self.notice(button_update(f"d1:{STUDENT}:home"))
        (call,) = self.send_message.call_args_list
        self.assertEqual(call.args, (STUDENT, "✨ New: the ▶️ Continue button at the bottom takes you back to where you were."))
        self.assertEqual([b.text for b in self.markup(call).keyboard[0]], ["🏠 Menu", "▶️ Continue"])
        self.assertEqual(student.get_student(STUDENT)["keyboard_version"], setup.KEYBOARD_VERSION)
        self.notice(text_update("hello"))
        setup._current.clear()  # even after a restart
        self.notice(text_update("hello"))
        self.assertEqual(len(self.send_message.call_args_list), 1)

    def test_persian_notice(self):
        self.old_student()
        student.set_language(STUDENT, "fa")
        self.notice(text_update("سلام"))
        call = self.send_message.call_args
        self.assertEqual(call.args[1], "✨ تازه: دکمه‌ی «▶️ ادامه» پایین صفحه تو رو می‌بره همون‌جا که بودی.")
        self.assertEqual([b.text for b in self.markup(call).keyboard[0]], ["▶️ ادامه", "🏠 منو"])

    def test_no_notice_in_groups_for_new_students_or_on_start(self):
        self.old_student()
        self.notice(text_update("/stats", chat_type="supergroup"))
        self.notice(button_update(f"d1:{STUDENT}:home", chat_type="supergroup"))
        self.notice(text_update("hi", user_id=7))  # new: setup brings the keyboard
        self.send_message.assert_not_called()
        # /start's welcome brings the keyboard, so it counts as told.
        run(home.start_command, text_update("/start"))
        self.assertEqual(student.get_student(STUDENT)["keyboard_version"], setup.KEYBOARD_VERSION)
        setup._current.clear()
        self.notice(text_update("hello"))
        self.send_message.assert_not_called()

    def test_registered_after_the_anonymous_check_and_before_the_screens(self):
        handlers = main.telegram_app.handlers[-1]
        callbacks = [getattr(h, "callback", None) for h in handlers]
        self.assertLess(callbacks.index(groups.anonymous_sender), callbacks.index(setup.keyboard_notice))
        self.assertIsInstance(handlers[callbacks.index(setup.keyboard_notice)], TypeHandler)
        self.old_student()
        with patch.object(main.telegram_app, "_initialized", True):
            asyncio.run(main.telegram_app.process_update(button_update(f"d1:{STUDENT}:c:math")))
        self.assertEqual(len(self.notices()), 1)
        self.assertTrue(self.edit_text.call_args.args[0].startswith("📐 Math"), "the button still works")

    def test_a_failure_is_only_logged(self):
        self.old_student()
        self.send_message.side_effect = RuntimeError("Telegram is down")
        with self.assertLogs("modules.ui.setup", "ERROR"):
            self.notice(text_update("hello"))


class SetupStorageTests(TelegramMocks):
    def test_finish_and_claim(self):
        self.assertFalse(student.claim_keyboard_version(STUDENT, 1), "no row: nothing to claim")
        student.set_language(STUDENT, "en")
        self.assertFalse(student.claim_keyboard_version(STUDENT, 1), "not set up yet")
        self.assertTrue(student.claim_keyboard_version(STUDENT, 1, only_set_up=False))
        self.assertTrue(student.finish_setup(STUDENT, 1))
        self.assertFalse(student.finish_setup(STUDENT, 1))
        self.assertEqual(student.get_student(STUDENT), {"language": "en", "level": None, "setup_done": True, "keyboard_version": 1})
        self.assertFalse(student.claim_keyboard_version(STUDENT, 1))
        self.assertTrue(student.claim_keyboard_version(STUDENT, 2))
