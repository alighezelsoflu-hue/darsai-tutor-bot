"""The speed limit in the chat (modules/ratelimit.py counts): "⏳ a bit slower" for a student doing too much at once.

Runs in group -2: after the activity tracker (-3), which still counts a slowed-down student as active, and before
the anonymous-sender check and the keyboard notice (-1) and every screen. Over the limit, ApplicationHandlerStop
ends the update here:
- a button press gets a pop-up every time (Telegram shows a spinner until a press is answered);
- a message or command gets one warning per window, and the rest are skipped without a word.

What counts is what /stats counts as activity (stats.counts_as_activity): button presses, messages in private
chats, and in groups commands and replies. Not the bot being added to a group, edited messages, bots, or posts
sent as the group or a channel (the anonymous-sender check answers those).
"""

import asyncio
import logging

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from modules import ratelimit, stats
from modules.i18n import t

from .core import student_language

logger = logging.getLogger(__name__)


async def refused_language(user) -> str:
    """The student's language, read once while they keep being refused: more refused taps cost no database read."""
    lang = ratelimit.ACTIONS.note(user.id)
    if lang is None:
        lang = await asyncio.to_thread(student_language, user.id, user.language_code)
        ratelimit.ACTIONS.set_note(user.id, lang)
    return lang


async def speed_limit(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not isinstance(update, Update) or not stats.counts_as_activity(update):
        return
    user = update.effective_user
    if ratelimit.ACTIONS.allow(user.id):
        return
    query = update.callback_query
    try:
        if query is not None:
            await query.answer(t(await refused_language(user), "rate.button"))
        elif ratelimit.ACTIONS.first_refusal(user.id):
            await update.effective_message.reply_text(t(await refused_language(user), "rate.message"))
    except Exception as error:
        # The update is skipped anyway; a failed "a bit slower" isn't worth an alert.
        logger.warning("Could not tell user %s to slow down: %s", user.id, error)
    raise ApplicationHandlerStop
