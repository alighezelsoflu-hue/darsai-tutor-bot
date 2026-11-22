"""The three setup questions for new students, and the one-time notice about the bottom keyboard.

New students (/start in a private chat, setup not done) answer three questions in one message: language,
level, first course. The last answer sends "✅ All set!" with the bottom keyboard and opens the course they
picked (a 🔜 course opens its 🔜 screen). Students the bot knew before the setup questions existed are
marked as done (migration 1 in modules/migrations.py), so they never see them.

Students who have done setup get the current bottom keyboard ([🏠 Menu] [▶️ Continue]) once, with a short
notice, the next time they use the bot in a private chat (keyboard_notice, before the screens). /start's
welcome and finishing setup bring the keyboard too, so they count. KEYBOARD_VERSION is the current one:
raise it when the bottom keyboard changes and add a new notice text.

Routes:
    su:l:<language>   question 1 answered: the interface language
    su:v:<level>      question 2 answered: the level
    su:c:<course>     question 3 answered: setup is done
"""

import asyncio
import logging
from contextlib import suppress
from typing import List, Set

from telegram import Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from config import BOT_NAME
from modules.courses import COURSES
from modules.i18n import LANGUAGE_NAMES, UI_LANGUAGES, level_label, t
from modules.math.shared import set_user_level
from modules.math.topics import LEVEL_ORDER
from modules.student import claim_keyboard_version, finish_setup, set_language

from .core import Screen, menu_reply_keyboard, student_language
from .courses import course_grid, course_view

logger = logging.getLogger(__name__)

KEYBOARD_VERSION = 1
# The language buttons in this order ("فارسی · English"), mirrored in Persian like every keyboard.
SETUP_LANGUAGES = ("fa", "en")

# Students this process doesn't need to check again: they have the current keyboard, or will get it when
# they finish setup. One database check per student per process.
_current: Set[int] = set()


# ------------------------------------------------------------
# The setup questions
# ------------------------------------------------------------

async def ask_language(screen: Screen) -> None:
    s = screen
    buttons = [s.button(LANGUAGE_NAMES[code], "su", "l", code) for code in SETUP_LANGUAGES]
    await s.send(s.t("setup.language", bot=BOT_NAME), s.keyboard([buttons]))


async def ask_level(screen: Screen) -> None:
    s = screen
    # One per row: some level names are too long for half a phone screen.
    rows = [[s.button(level_label(s.lang, level), "su", "v", level)] for level in LEVEL_ORDER]
    await s.show(s.t("setup.level"), s.keyboard(rows))


async def ask_course(screen: Screen) -> None:
    await screen.show(screen.t("setup.course"), screen.keyboard(course_grid(screen, "su", "c")))


async def finish(screen: Screen, course_id: str) -> None:
    first = await asyncio.to_thread(finish_setup, screen.user_id, KEYBOARD_VERSION)
    _current.add(screen.user_id)
    if not first:
        # A second tap on a setup button: setup is already done, so just open the course.
        await screen.show(*await course_view(screen, course_id))
        return
    if screen.query is not None:
        # The question is answered: its buttons go, and the course opens in a new message below.
        with suppress(TelegramError):
            await screen.query.edit_message_reply_markup(reply_markup=None)
    # A separate message, because one message can't carry both the bottom keyboard and inline buttons.
    await screen.send(screen.t("setup.done"), menu_reply_keyboard(screen.lang))
    await screen.send(*await course_view(screen, course_id))


async def setup_route(screen: Screen, args: List[str]) -> None:
    action = args[0] if args else ""
    value = args[1] if len(args) > 1 else ""
    if action == "l" and value in UI_LANGUAGES:
        await asyncio.to_thread(set_language, screen.user_id, value)
        screen.lang = value
        await ask_level(screen)
    elif action == "v" and value in LEVEL_ORDER:
        await asyncio.to_thread(set_user_level, screen.chat_id, screen.user_id, value)
        await ask_course(screen)
    elif action == "c" and value in COURSES:
        await finish(screen, value)
    else:
        await screen.answer(screen.t("toast.expired"))


# ------------------------------------------------------------
# The bottom keyboard
# ------------------------------------------------------------

async def keyboard_brought(user_id: int, version: int) -> None:
    """A message with the current bottom keyboard is on its way to the student (/start's welcome)."""
    if version < KEYBOARD_VERSION:
        await asyncio.to_thread(claim_keyboard_version, user_id, KEYBOARD_VERSION, False)
    _current.add(user_id)


async def keyboard_notice(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Before the screens: send the current bottom keyboard once to students who have done setup.

    Private chats only. A failure is only logged, so the student's button or message is still handled.
    """
    if not isinstance(update, Update):
        return
    user, chat = update.effective_user, update.effective_chat
    if user is None or chat is None or user.is_bot or chat.type != ChatType.PRIVATE or user.id in _current:
        return
    message = update.message
    if update.callback_query is None and message is None:
        return  # e.g. the student blocked the bot, or edited a message
    if message is not None and (message.text or "").startswith("/start"):
        return  # /start's welcome brings the keyboard
    try:
        claimed = await asyncio.to_thread(claim_keyboard_version, user.id, KEYBOARD_VERSION)
        _current.add(user.id)
        if claimed:
            lang = await asyncio.to_thread(student_language, user.id, user.language_code)
            await context.bot.send_message(chat.id, t(lang, "keyboard.notice"), reply_markup=menu_reply_keyboard(lang))
    except Exception:
        logger.exception("Could not send the bottom keyboard notice to user %s", user.id)
