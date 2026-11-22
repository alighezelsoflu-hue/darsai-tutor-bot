"""📊 My progress: mastery of every topic the student practised (in any chat), and a suggested next topic.

Route: prog
"""

import asyncio
from typing import List

from modules.i18n import level_label, local_digits
from modules.math.shared import get_mastery, get_user_level
from modules.math.topics import LEVEL_ORDER, topics_for_level

from .core import Screen
from .practice import mastery_bar, owner_line, percent, topic_name


async def show_progress(screen: Screen) -> None:
    level = await asyncio.to_thread(get_user_level, screen.chat_id, screen.user_id)
    mastery = await asyncio.to_thread(get_mastery, screen.user_id)
    s = screen
    title = owner_line(s) + s.t("progress.title")

    sections: List[str] = []
    for section_level in LEVEL_ORDER:
        lines = []
        for topic in topics_for_level(section_level):
            entry = mastery.get((section_level, topic))
            if entry and entry["correct"] + entry["wrong"]:
                lines.append(s.t(
                    "progress.topic",
                    topic=topic_name(s, topic),
                    bar=mastery_bar(entry["mastery"]),
                    percent=percent(s, entry["mastery"]),
                    correct=local_digits(s.lang, entry["correct"]),
                    wrong=local_digits(s.lang, entry["wrong"]),
                ))
            elif section_level == level:
                # The student's own level also lists the topics they haven't started.
                lines.append(s.t("practice.topic_new", topic=topic_name(s, topic)))
        if lines:
            sections.append(f"🎓 {level_label(s.lang, section_level)}\n" + "\n".join(lines))

    if not any(entry["correct"] + entry["wrong"] for entry in mastery.values()):
        await s.show(f"{title}\n\n{s.t('progress.empty')}", s.keyboard([
            [s.button(s.t("btn.practice"), "prac"), s.button(s.t("btn.menu"), "home")],
        ]))
        return

    # Suggest the weakest topic of the student's level (a topic not started counts as 0%).
    own_topics = topics_for_level(level)
    suggested = min(own_topics, key=lambda topic: mastery.get((level, topic), {}).get("mastery", 0.0))
    text = "\n\n".join([title] + sections + [s.t("progress.suggest", topic=topic_name(s, suggested))])
    await s.show(text, s.keyboard([
        [s.button(s.t("btn.practice_named", topic=topic_name(s, suggested)), "prac", "n", suggested)],
        [s.button(s.t("btn.menu"), "home")],
    ]))


async def progress_route(screen: Screen, args: List[str]) -> None:
    await show_progress(screen)
