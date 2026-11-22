"""Practice: pick a topic, type the answer, get one more try, then the solution.

The difficulty follows the student's mastery of the topic, unless they press 🔽 Easier or 🔼 Harder,
which keeps that difficulty until they pick a topic again.

Routes (after "prac" in the callback data):
    prac                       the topics of the student's level, with their mastery
    prac:n:<topic>[:<mode>]    a new question. Mode "a" (default) follows mastery; e, m, h pin a difficulty.
    prac:s:<question id>       show the solution. Counts as a missed question.

In private chats typed text is the answer (unless a tool such as Solve is open, see typed.py).
In groups the student replies to the question.
"""

import asyncio
import secrets
import time
from typing import Dict, List, Optional

from telegram import InlineKeyboardMarkup

from modules.i18n import is_rtl, level_label, local_digits
from modules.input_mode import clear_input_mode
from modules.math.shared import (
    DIFFICULTIES,
    answer_count,
    answers_match,
    clear_active_question,
    get_active_question,
    get_mastery,
    get_user_level,
    readable_answer,
    recommended_difficulty,
    record_answer,
    save_active_question,
    update_active_question,
)
from modules.math.topics import TOPIC_LEVEL, get_topic_module, topics_for_level

from .core import Screen, copyable

LRM = "\u200e"  # left-to-right mark
AUTO = "a"
MODE_DIFFICULTY = {"e": "easy", "m": "medium", "h": "hard"}
DIFFICULTY_MODE = {difficulty: mode for mode, difficulty in MODE_DIFFICULTY.items()}
# After this long, typed text is no longer taken as the answer to an old question.
QUESTION_MAX_AGE_SECONDS = 24 * 60 * 60
BAR_LENGTH = 10
TWO_ANSWERS_EXAMPLE = "2, -3"
HEADLINES = {
    "first_try": "practice.correct",
    "second_try": "practice.correct_second",
    "missed": "practice.missed",
}


# ------------------------------------------------------------
# Text
# ------------------------------------------------------------

def formulas(screen: Screen, lines: List[str], copy: bool = False) -> str:
    """Formulas on their own lines. In right-to-left languages each line starts with a left-to-right mark.

    copy=True sends each line as code, so one tap copies just that line (for examples students can send).
    """
    prefix = LRM if is_rtl(screen.lang) else ""
    return "\n".join(prefix + (copyable(line) if copy else line) for line in lines)


def topic_name(screen: Screen, topic: str) -> str:
    try:
        return screen.t(f"topic.{topic}")
    except KeyError:
        return topic


def mastery_bar(mastery: float) -> str:
    filled = round(mastery * BAR_LENGTH)
    return "▰" * filled + "▱" * (BAR_LENGTH - filled)


def percent(screen: Screen, mastery: float) -> str:
    return local_digits(screen.lang, int(round(mastery * 100)))


def owner_line(screen: Screen) -> str:
    """In a group, whose question or menu this is."""
    return "" if screen.private else f"👤 {screen.user.first_name}\n"


def question_text(screen: Screen, question: Dict) -> str:
    header = screen.t(
        "practice.header",
        topic=topic_name(screen, question["topic"]),
        difficulty=screen.t(f"difficulty.{question['difficulty']}"),
    )
    prompt = screen.t(f"prompt.{question['prompt']}")
    return f"{owner_line(screen)}{header}\n\n{prompt}\n{formulas(screen, question['formula'])}"


def two_answers_hint(screen: Screen) -> str:
    return screen.t("practice.two_answers") + "\n" + formulas(screen, [TWO_ANSWERS_EXAMPLE], copy=True)


def answer_example(question: Dict) -> str:
    if answer_count(question["answer"]) > 1:
        return TWO_ANSWERS_EXAMPLE
    return "6x + 5" if question["prompt"] == "derivative" else "5"


def solution_text(screen: Screen, question: Dict) -> str:
    lines = [screen.t("practice.solution")]
    for key, params, formula in question["steps"]:
        prose = {name: local_digits(screen.lang, value) for name, value in params.items()}
        lines.append(screen.t(f"step.{key}", **prose))
        lines.append(formulas(screen, [formula]))
    return "\n".join(lines)


def mastery_text(screen: Screen, question: Dict, before: float, after: float) -> str:
    change = int(round(after * 100)) - int(round(before * 100))
    change_text = f" ({'↑' if change > 0 else '↓'}{local_digits(screen.lang, abs(change))})" if change else ""
    text = screen.t(
        "practice.mastery",
        topic=topic_name(screen, question["topic"]),
        bar=mastery_bar(after),
        percent=percent(screen, after),
        change=change_text,
    )
    if question["mode"] == AUTO:
        coming = recommended_difficulty(after)
        if coming != question["difficulty"]:
            harder = DIFFICULTIES.index(coming) > DIFFICULTIES.index(question["difficulty"])
            key = "practice.next_harder" if harder else "practice.next_easier"
            text += "\n" + screen.t(key, difficulty=screen.t(f"difficulty.{coming}"))
    return text


# ------------------------------------------------------------
# Keyboards
# ------------------------------------------------------------

def question_keyboard(screen: Screen, question: Dict) -> InlineKeyboardMarkup:
    s = screen
    return s.keyboard([
        [
            s.button(s.t("btn.show_solution"), "prac", "s", question["id"]),
            s.button(s.t("btn.skip"), "prac", "n", question["topic"], question["mode"]),
        ],
        [s.button(s.t("btn.topics"), "prac"), s.button(s.t("btn.menu"), "home")],
    ])


def solution_keyboard(screen: Screen, question: Dict) -> InlineKeyboardMarkup:
    return screen.keyboard([[screen.button(screen.t("btn.show_solution"), "prac", "s", question["id"])]])


def result_keyboard(screen: Screen, question: Dict) -> InlineKeyboardMarkup:
    s = screen
    topic = question["topic"]
    index = DIFFICULTIES.index(question["difficulty"])
    other_difficulty = []
    if index > 0:
        other_difficulty.append(s.button(s.t("btn.easier"), "prac", "n", topic, DIFFICULTY_MODE[DIFFICULTIES[index - 1]]))
    if index < len(DIFFICULTIES) - 1:
        other_difficulty.append(s.button(s.t("btn.harder"), "prac", "n", topic, DIFFICULTY_MODE[DIFFICULTIES[index + 1]]))
    return s.keyboard([
        [s.button(s.t("btn.next"), "prac", "n", topic, question["mode"])],
        other_difficulty,
        [s.button(s.t("btn.topics"), "prac"), s.button(s.t("btn.menu"), "home")],
    ])


# ------------------------------------------------------------
# Screens
# ------------------------------------------------------------

async def show_topics(screen: Screen) -> None:
    level = await asyncio.to_thread(get_user_level, screen.chat_id, screen.user_id)
    mastery = await asyncio.to_thread(get_mastery, screen.user_id)
    topics = topics_for_level(level)
    lines = [owner_line(screen) + screen.t("practice.topics", level=level_label(screen.lang, level))]
    for topic in topics:
        entry = mastery.get((level, topic))
        if entry and entry["correct"] + entry["wrong"]:
            lines.append(screen.t(
                "practice.topic_progress",
                topic=topic_name(screen, topic),
                bar=mastery_bar(entry["mastery"]),
                percent=percent(screen, entry["mastery"]),
            ))
        else:
            lines.append(screen.t("practice.topic_new", topic=topic_name(screen, topic)))
    rows = [[screen.button(topic_name(screen, topic), "prac", "n", topic)] for topic in topics]
    rows.append([screen.button(screen.t("btn.menu"), "home")])
    await screen.show("\n".join(lines), screen.keyboard(rows))


async def new_question(screen: Screen, topic: str, mode: str = AUTO) -> None:
    """Show a new question (replacing the pressed message) and make it the student's active question."""
    level = TOPIC_LEVEL[topic]
    difficulty = MODE_DIFFICULTY.get(mode)
    if difficulty is None:
        mode = AUTO
        mastery = await asyncio.to_thread(get_mastery, screen.user_id)
        difficulty = recommended_difficulty(mastery.get((level, topic), {}).get("mastery", 0.0))
    question = get_topic_module(level, topic).practice(difficulty)
    question.update(id=secrets.token_hex(4), mode=mode, attempts=0, asked_at=time.time())

    instructions = screen.t("practice.type_answer" if screen.private else "practice.reply_answer")
    if answer_count(question["answer"]) > 1:
        instructions += "\n" + two_answers_hint(screen)
    message_id = await screen.show(f"{question_text(screen, question)}\n\n{instructions}", question_keyboard(screen, question))
    # In groups only replies to these messages count as answers.
    question["message_ids"] = [message_id] if message_id is not None else []
    await asyncio.to_thread(save_active_question, screen.chat_id, screen.user_id, question)
    # Typed text answers this question now, even if a tool (tutor, Solve, Plot) was open.
    await asyncio.to_thread(clear_input_mode, screen.chat_id, screen.user_id)


async def finish(screen: Screen, question: Dict, outcome: str, from_button: bool = False) -> None:
    """Count the result once, then show the solution and the student's new mastery."""
    removed = await asyncio.to_thread(clear_active_question, screen.chat_id, screen.user_id, question["id"])
    if not removed:
        # Another answer or button press finished this question a moment ago.
        await screen.answer(screen.t("toast.question_over"))
        return
    before, after = await asyncio.to_thread(
        record_answer, screen.user_id, question["level"], question["topic"], question["difficulty"], outcome
    )
    first = question_text(screen, question) if from_button else screen.t(HEADLINES[outcome])
    text = f"{first}\n\n{solution_text(screen, question)}\n\n{mastery_text(screen, question, before, after)}"
    pressed = None
    if from_button:
        pressed = await screen.show(text, result_keyboard(screen, question))
    else:
        await screen.send(text, result_keyboard(screen, question))
    # The finished question's other messages keep no buttons (the pressed one now shows the result).
    for message_id in question.get("message_ids", []):
        if message_id != pressed:
            await screen.remove_buttons(message_id)


async def show_solution(screen: Screen, question_id: str) -> None:
    question = await asyncio.to_thread(get_active_question, screen.chat_id, screen.user_id)
    if not question or question.get("id") != question_id:
        await screen.answer(screen.t("toast.question_over"))
        return
    await finish(screen, question, "missed", from_button=True)


async def practice_route(screen: Screen, args: List[str]) -> None:
    action = args[0] if args else ""
    if action == "n" and len(args) > 1 and args[1] in TOPIC_LEVEL:
        await new_question(screen, args[1], args[2] if len(args) > 2 else AUTO)
    elif action == "s" and len(args) > 1:
        await show_solution(screen, args[1])
    else:
        await show_topics(screen)


# ------------------------------------------------------------
# Typed answers
# ------------------------------------------------------------

async def active_question(chat_id: int, user_id: int) -> Optional[Dict]:
    """The question the student is working on in this chat, unless it is more than a day old."""
    question = await asyncio.to_thread(get_active_question, chat_id, user_id)
    if not question or "steps" not in question:
        return None
    if time.time() - float(question.get("asked_at", 0)) > QUESTION_MAX_AGE_SECONDS:
        return None
    return question


async def handle_answer(screen: Screen, question: Dict, text: str) -> None:
    if not readable_answer(text):
        # Not an attempt: the student gets told how to write an answer and keeps both tries.
        hint = screen.t("practice.unreadable") + "\n" + formulas(screen, [answer_example(question)], copy=True)
        sent = await screen.send(hint, solution_keyboard(screen, question))
        await remember_message(screen, question, sent.message_id)
        return
    if answers_match(question["answer"], text):
        await finish(screen, question, "second_try" if question.get("attempts") else "first_try")
        return
    if question.get("attempts"):
        await finish(screen, question, "missed")
        return
    question["attempts"] = 1
    lines = [screen.t("practice.try_again"), screen.t("practice.type_again" if screen.private else "practice.reply_again")]
    expected = answer_count(question["answer"])
    if expected > 1 and answer_count(text) != expected:
        lines.append(two_answers_hint(screen))
    sent = await screen.send("\n".join(lines), solution_keyboard(screen, question))
    await remember_message(screen, question, sent.message_id)


async def remember_message(screen: Screen, question: Dict, message_id: int) -> None:
    """Save the question with one more message that belongs to it (and the try just counted).

    In groups, replies to that message count as answers, and its buttons go when the question is finished.
    """
    question.setdefault("message_ids", []).append(message_id)
    saved = await asyncio.to_thread(update_active_question, screen.chat_id, screen.user_id, question)
    if not saved:
        # Show solution or another answer finished it a moment ago: this message's button is stale already.
        await screen.remove_buttons(message_id)

