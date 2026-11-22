"""Building blocks for the button interface.

Every button's callback data is "d1:<owner user id>:<route>[:<arg>...]":
- "d1" is the format version, so a later format can recognise old buttons.
- The owner id stops other people in a group from pressing someone else's buttons.
Telegram allows at most 64 bytes of callback data; pack() enforces it.
"""

import asyncio
import logging
from contextlib import suppress
from typing import List, Optional, Sequence, Tuple

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatType
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from modules.i18n import UI_LANGUAGES, detect_language, is_rtl, t
from modules.student import get_student

logger = logging.getLogger(__name__)

CALLBACK_PREFIX = "d1"
MAX_CALLBACK_BYTES = 64


def pack(owner_id: int, *route: str) -> str:
    data = ":".join((CALLBACK_PREFIX, str(owner_id)) + tuple(route))
    if len(data.encode("utf-8")) > MAX_CALLBACK_BYTES:
        raise ValueError(f"Callback data is longer than {MAX_CALLBACK_BYTES} bytes: {data!r}")
    return data


def unpack(data: Optional[str]) -> Optional[Tuple[int, List[str]]]:
    """(owner id, route) for our own buttons, None for anything else."""
    parts = (data or "").split(":")
    if len(parts) < 3 or parts[0] != CALLBACK_PREFIX:
        return None
    try:
        owner_id = int(parts[1])
    except ValueError:
        return None
    return owner_id, parts[2:]


def arrange(lang: str, rows: Sequence[Sequence[InlineKeyboardButton]]) -> List[List[InlineKeyboardButton]]:
    """Telegram does not mirror keyboards. In right-to-left languages the first button belongs on the right."""
    return [list(reversed(row)) if is_rtl(lang) else list(row) for row in rows]


def menu_reply_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """The 🏠 Menu button that stays at the bottom of private chats."""
    return ReplyKeyboardMarkup([[KeyboardButton(t(lang, "btn.menu"))]], resize_keyboard=True, is_persistent=True)


# A student may still have the button from before they changed language, so accept every label.
MENU_LABELS = frozenset(t(lang, "btn.menu") for lang in UI_LANGUAGES)


def student_language(user_id: int, telegram_language_code: Optional[str]) -> str:
    """Blocking. The language the student chose, or a guess from their Telegram settings."""
    saved = get_student(user_id)["language"]
    return saved if saved in UI_LANGUAGES else detect_language(telegram_language_code)


class Screen:
    """Who a screen is drawn for, plus helpers to draw it."""

    def __init__(self, update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
        self.update = update
        self.context = context
        self.lang = lang
        self.user = update.effective_user
        self.chat = update.effective_chat
        self.user_id = self.user.id
        self.chat_id = self.chat.id
        self.private = self.chat.type == ChatType.PRIVATE
        self.query = update.callback_query
        self._answered = False

    @classmethod
    async def load(cls, update: Update, context: ContextTypes.DEFAULT_TYPE) -> "Screen":
        user = update.effective_user
        lang = await asyncio.to_thread(student_language, user.id, user.language_code)
        return cls(update, context, lang)

    def t(self, key: str, **params) -> str:
        return t(self.lang, key, **params)

    def button(self, label: str, *route: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(label, callback_data=pack(self.user_id, *route))

    def keyboard(self, rows: Sequence[Sequence[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(arrange(self.lang, rows))

    async def answer(self, text: Optional[str] = None) -> None:
        """Answer the button press once (Telegram shows a spinner until it is answered)."""
        if self.query is not None and not self._answered:
            self._answered = True
            await self.query.answer(text)

    async def send(self, text: str, markup=None):
        """Send a new message. Replies to the student's message when there is one."""
        if self.query is None and self.update.effective_message is not None:
            return await self.update.effective_message.reply_text(text, reply_markup=markup)
        return await self.context.bot.send_message(self.chat_id, text, reply_markup=markup)

    async def remove_buttons(self, message_id: int) -> None:
        """Take the inline buttons off one of the bot's messages in this chat. A failure is only logged."""
        try:
            await self.context.bot.edit_message_reply_markup(chat_id=self.chat_id, message_id=message_id, reply_markup=None)
        except TelegramError as error:
            # E.g. the message was deleted or already has no buttons. The buttons would only show a pop-up.
            logger.info("Could not remove buttons from message %s: %s", message_id, error)

    async def show(self, text: str, markup: Optional[InlineKeyboardMarkup] = None) -> int:
        """Replace the message whose button was pressed. Send a new message when it can't be edited.

        Returns the id of the message that shows the screen now.
        """
        message = self.query.message if self.query is not None else None
        if isinstance(message, Message) and message.text is not None:
            try:
                await self.query.edit_message_text(text, reply_markup=markup)
                return message.message_id
            except BadRequest as error:
                if "not modified" in str(error).lower():
                    return message.message_id
                logger.warning("Could not edit message, sending a new one: %s", error)
        elif isinstance(message, Message):
            # A photo can't turn into a text message. Retire its buttons and send a new message instead.
            with suppress(BadRequest):
                await self.query.edit_message_reply_markup(reply_markup=None)
        sent = await self.send(text, markup)
        return sent.message_id
