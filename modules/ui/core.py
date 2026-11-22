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
    MessageEntity,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction, ChatType
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from modules.common import split_message
from modules.i18n import UI_LANGUAGES, detect_language, is_rtl, t
from modules.student import get_student

logger = logging.getLogger(__name__)

CALLBACK_PREFIX = "d1"
MAX_CALLBACK_BYTES = 64

# Text between these two private-use characters is sent as code (monospace). Telegram copies code with
# one tap, so examples are copyable on their own. Messages stay plain text: no parse_mode, nothing to escape.
CODE_OPEN, CODE_CLOSE = "\ue000", "\ue001"


def copyable(text: str) -> str:
    """Mark text to be sent as code. Any marks inside it (e.g. typed by a student) are dropped."""
    clean = text.replace(CODE_OPEN, "").replace(CODE_CLOSE, "")
    return f"{CODE_OPEN}{clean}{CODE_CLOSE}" if clean else ""


def with_entities(text: str) -> Tuple[str, Optional[List[MessageEntity]]]:
    """Remove the code marks and return the text with Telegram code entities for the marked parts.

    Entity offsets and lengths count UTF-16 code units, as Telegram does (an emoji counts 2).
    """
    if CODE_OPEN not in text and CODE_CLOSE not in text:
        return text, None
    parts: List[str] = []
    entities: List[MessageEntity] = []
    offset, start = 0, None
    for char in text:
        if char == CODE_OPEN:
            start = offset
        elif char == CODE_CLOSE:
            if start is not None and offset > start:
                entities.append(MessageEntity(MessageEntity.CODE, start, offset - start))
            start = None
        else:
            parts.append(char)
            offset += len(char.encode("utf-16-le")) // 2
    return "".join(parts), entities or None


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
        pressed = self.query.message if self.query is not None else None
        # In a forum group, messages sent after a button press go to the topic where it was pressed.
        self.thread_id = pressed.message_thread_id if isinstance(pressed, Message) and pressed.is_topic_message else None
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
        text, entities = with_entities(text)
        if self.query is None and self.update.effective_message is not None:
            return await self.update.effective_message.reply_text(text, reply_markup=markup, entities=entities)
        return await self.context.bot.send_message(
            self.chat_id, text, reply_markup=markup, message_thread_id=self.thread_id, entities=entities
        )

    async def send_long(self, text: str, markup=None) -> int:
        """Send text of any length (AI answers), split into Telegram-sized messages. The buttons go on the last one.

        Returns the id of the last message.
        """
        chunks = split_message(text) or [self.t("ai.unavailable")]
        for index, chunk in enumerate(chunks):
            sent = await self.send(chunk, markup if index == len(chunks) - 1 else None)
        return sent.message_id

    async def send_photo(self, photo, caption: str, markup=None):
        """Send a photo. Replies to the student's message when there is one."""
        caption, entities = with_entities(caption)
        if self.query is None and self.update.effective_message is not None:
            return await self.update.effective_message.reply_photo(
                photo, caption=caption, reply_markup=markup, caption_entities=entities
            )
        return await self.context.bot.send_photo(
            self.chat_id, photo, caption=caption, reply_markup=markup, message_thread_id=self.thread_id,
            caption_entities=entities,
        )

    async def typing(self) -> None:
        """Show "typing…" in the chat while something slow (the AI tutor) runs."""
        with suppress(TelegramError):
            await self.context.bot.send_chat_action(self.chat_id, ChatAction.TYPING)

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
                plain, entities = with_entities(text)
                await self.query.edit_message_text(plain, reply_markup=markup, entities=entities)
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
