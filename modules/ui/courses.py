"""Course screens: each live course's hub, the 🔜 screens with 🔔 Notify me, and ▶️ Continue.

The courses themselves are in modules/courses.py.

Routes:
    c:<course>                   a live course's hub, or a coming-soon course's 🔜 screen
    c:<course>:n                 🔔 Notify me on a 🔜 screen
    c:math:<screen>[:<arg>…]     a Math screen: learn, prac, tutor, solve, plot (see their modules)
    c:math:konkur[:n]            🎯 Konkur Math 🔜: the Konkur 🔜 screen, with 🔙 Math
    cont                         ▶️ Continue (the bottom keyboard's ▶️ Continue does the same)
"""

import asyncio
from typing import Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from modules.courses import COURSES, EXAMS, GRID
from modules.input_mode import clear_input_mode
from modules.math.shared import get_mastery, get_user_level, recommended_difficulty
from modules.math.topics import TOPIC_LEVEL, topics_for_level
from modules.notify import add_notice, wants_notice

from . import learn, practice, tools
from .core import Screen
from .practice import back_button, mastery_bar, owner_line, percent, topic_name, weakest_topic, where

# The screens behind a live course's hub: c:<course>:<screen>[:<arg>…]
SCREENS = {
    "math": {
        "learn": learn.learn_route,
        "prac": practice.practice_route,
        "tutor": tools.tutor_route,
        "solve": tools.solve_route,
        "plot": tools.plot_route,
    },
}
# Hub buttons other than "next": (label key, screen).
HUB_BUTTONS = {
    "learn": ("btn.learn", "learn"),
    "prac": ("btn.practice", "prac"),
    "konkur": ("btn.konkur_course", "konkur"),
    "tutor": ("btn.tutor", "tutor"),
    "solve": ("btn.solve", "solve"),
    "plot": ("btn.plot", "plot"),
}


def course_grid(screen: Screen, *route: str) -> List[List[InlineKeyboardButton]]:
    """Two courses per row, then each exam course on its own row. Each button's route is route + course id."""
    s = screen
    buttons = [s.button(COURSES[course_id].label(s.lang), *route, course_id) for course_id in GRID]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows += [[s.button(COURSES[course_id].label(s.lang), *route, course_id)] for course_id in EXAMS]
    return rows


# ------------------------------------------------------------
# A live course's hub
# ------------------------------------------------------------

async def hub_view(screen: Screen, course_id: str) -> Tuple[str, InlineKeyboardMarkup]:
    course = COURSES[course_id]
    s = screen
    level = await asyncio.to_thread(get_user_level, s.chat_id, s.user_id)
    mastery = await asyncio.to_thread(get_mastery, s.user_id)
    values = [mastery.get((level, topic), {}).get("mastery", 0.0) for topic in topics_for_level(level)]
    overall = sum(values) / len(values) if values else 0.0
    suggested = weakest_topic(level, mastery)
    difficulty = recommended_difficulty(mastery.get((level, suggested), {}).get("mastery", 0.0))
    text = "\n".join([
        owner_line(s) + f"{course.emoji} {where(s, level, course=course_id)}",
        s.t("hub.mastery", bar=mastery_bar(overall), percent=percent(s, overall)),
        s.t("hub.suggested", topic=topic_name(s, suggested), difficulty=s.t(f"difficulty.{difficulty}")),
    ])
    rows: List[List[InlineKeyboardButton]] = []
    pair: List[InlineKeyboardButton] = []
    for item in course.hub:
        if item == "next":
            label = s.t("btn.practice_next", topic=topic_name(s, suggested))
            rows.append([s.button(label, "c", course_id, "prac", "n", suggested)])
            continue
        key, screen_name = HUB_BUTTONS[item]
        pair.append(s.button(s.t(key, course=course.name(s.lang)), "c", course_id, screen_name))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([s.button(s.t("btn.menu"), "home")])
    return text, s.keyboard(rows)


async def show_hub(screen: Screen, course_id: str) -> None:
    # Leaving a tool (🔙 Math): typed text no longer goes to the tutor, Solve or Plot.
    await asyncio.to_thread(clear_input_mode, screen.chat_id, screen.user_id)
    await screen.show(*await hub_view(screen, course_id))


# ------------------------------------------------------------
# 🔜 Coming soon
# ------------------------------------------------------------

def soon_view(screen: Screen, course_id: str, notified: bool, parent: Optional[str] = None) -> Tuple[str, InlineKeyboardMarkup]:
    """A coming-soon course. parent is the live course it was opened from (🎯 Konkur Math in Math)."""
    s = screen
    text = owner_line(s) + s.t(f"soon.{course_id}") + "\n\n" + s.t("soon.saved" if notified else "soon.ask")
    route = ("c", parent, course_id) if parent else ("c", course_id)
    rows = [] if notified else [[s.button(s.t("btn.notify"), *route, "n")]]
    rows.append([back_button(s) if parent == "math" else s.button(s.t("btn.menu"), "home")])
    return text, s.keyboard(rows)


async def soon_route(screen: Screen, course_id: str, args: List[str], parent: Optional[str] = None) -> None:
    if args[:1] == ["n"]:
        await asyncio.to_thread(add_notice, screen.user_id, course_id, screen.lang)
        await screen.answer(screen.t("toast.notify_saved"))
        notified = True
    else:
        notified = await asyncio.to_thread(wants_notice, screen.user_id, course_id)
    await screen.show(*soon_view(screen, course_id, notified, parent))


async def course_view(screen: Screen, course_id: str) -> Tuple[str, InlineKeyboardMarkup]:
    """The screen a course button opens: the hub, or the 🔜 screen."""
    if COURSES[course_id].live:
        return await hub_view(screen, course_id)
    notified = await asyncio.to_thread(wants_notice, screen.user_id, course_id)
    return soon_view(screen, course_id, notified)


async def course_route(screen: Screen, args: List[str]) -> None:
    course_id = args[0] if args else ""
    course = COURSES.get(course_id)
    if course is None:
        await screen.answer(screen.t("toast.expired"))
        return
    if not course.live:
        await soon_route(screen, course_id, args[1:])
        return
    name, rest = (args[1], args[2:]) if len(args) > 1 else ("", [])
    if name == "konkur" and "konkur" in course.hub:
        await soon_route(screen, "konkur", rest, parent=course_id)
        return
    handler = SCREENS.get(course_id, {}).get(name)
    if handler is None:
        await show_hub(screen, course_id)
        return
    await handler(screen, rest)


# ------------------------------------------------------------
# ▶️ Continue
# ------------------------------------------------------------

async def continue_target(screen: Screen) -> Tuple[bool, Optional[Dict], str]:
    """(continuing, question, topic). In this order:

    1. the student's unfinished practice question in this chat (less than a day old): reopen it,
    2. else the topic they practised last: a new question in it,
    3. else (nothing practised yet, continuing=False) the weakest topic of their level, to ▶️ Start.
    """
    question = await practice.active_question(screen.chat_id, screen.user_id)
    if question and question.get("topic") in TOPIC_LEVEL:
        return True, question, question["topic"]
    mastery = await asyncio.to_thread(get_mastery, screen.user_id)
    for (_, topic), entry in mastery.items():  # most recently practised first
        if topic in TOPIC_LEVEL and entry["correct"] + entry["wrong"]:
            return True, None, topic
    level = await asyncio.to_thread(get_user_level, screen.chat_id, screen.user_id)
    return False, None, weakest_topic(level, mastery)


async def continue_route(screen: Screen, args: List[str]) -> None:
    _, question, topic = await continue_target(screen)
    if question:
        await practice.reopen_question(screen, question)
    else:
        await practice.new_question(screen, topic)
