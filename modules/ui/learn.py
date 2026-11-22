"""📘 Learn: a short lesson per topic, with a worked example, then Practice or Ask the tutor about it.

Routes (after "learn" in the callback data):
    learn            the topics of the student's level
    learn:<topic>    the lesson
"""

import asyncio
from typing import Dict, List

from modules.i18n import level_label, local_digits
from modules.math.shared import get_user_level
from modules.math.topics import TOPIC_LEVEL, get_topic_module, topics_for_level

from .core import Screen
from .practice import formulas, owner_line, solution_text, topic_name


def lesson_text(screen: Screen, lesson: Dict) -> str:
    parts = [f"{owner_line(screen)}📘 {topic_name(screen, lesson['topic'])}"]
    for key, params, formula in lesson["intro"]:
        prose = screen.t(key, **{name: local_digits(screen.lang, value) for name, value in params.items()})
        parts.append(prose + ("\n" + formulas(screen, [formula]) if formula else ""))
    example = lesson["example"]
    parts.append(
        screen.t("learn.example") + "\n"
        + screen.t(f"prompt.{example['prompt']}") + "\n"
        + formulas(screen, example["formula"])
    )
    parts.append(solution_text(screen, example))
    return "\n\n".join(parts)


async def show_topics(screen: Screen) -> None:
    level = await asyncio.to_thread(get_user_level, screen.chat_id, screen.user_id)
    topics = topics_for_level(level)
    text = owner_line(screen) + screen.t("learn.topics", level=level_label(screen.lang, level))
    rows = [[screen.button(topic_name(screen, topic), "learn", topic)] for topic in topics]
    rows.append([screen.button(screen.t("btn.menu"), "home")])
    await screen.show(text, screen.keyboard(rows))


async def show_lesson(screen: Screen, topic: str) -> None:
    lesson = get_topic_module(TOPIC_LEVEL[topic], topic).lesson()
    s = screen
    await s.show(lesson_text(s, lesson), s.keyboard([
        [s.button(s.t("btn.practice_topic"), "prac", "n", topic), s.button(s.t("btn.tutor"), "tutor", topic)],
        [s.button(s.t("btn.learn_topics"), "learn"), s.button(s.t("btn.menu"), "home")],
    ]))


async def learn_route(screen: Screen, args: List[str]) -> None:
    if args and args[0] in TOPIC_LEVEL:
        await show_lesson(screen, args[0])
    else:
        await show_topics(screen)
