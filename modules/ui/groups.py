"""Group chats: a greeting when the bot is added, and a note for people who post anonymously.

Each student gets their own menu with /start, and the bot only sees commands and replies to its own
messages (privacy mode), so the greeting says exactly that.
"""

import asyncio

from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ApplicationHandlerStop, ContextTypes

from config import BOT_NAME
from modules.i18n import t

from .core import student_language

GROUP_TYPES = (ChatType.GROUP, ChatType.SUPERGROUP)
OUTSIDE = (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)


async def bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The bot's own membership changed. Greet the group when it was just added."""
    change = update.my_chat_member
    if not change or change.chat.type not in GROUP_TYPES:
        return
    if change.old_chat_member.status not in OUTSIDE or change.new_chat_member.status in OUTSIDE:
        return  # e.g. promoted to admin, or removed
    adder = change.from_user
    lang = await asyncio.to_thread(student_language, adder.id, adder.language_code)
    await context.bot.send_message(change.chat.id, t(lang, "group.welcome", bot=BOT_NAME))


async def anonymous_sender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A command or reply sent as the group (anonymous admin) or as a channel.

    All of these share one Telegram user id, so they would share one menu, one practice question and one
    daily tutor limit. Ask them to post as themselves, in both languages (we don't know theirs).
    """
    message = update.effective_message
    if message:
        await message.reply_text(
            t("en", "group.anonymous", bot=BOT_NAME) + "\n\n" + t("fa", "group.anonymous", bot=BOT_NAME)
        )
    raise ApplicationHandlerStop
