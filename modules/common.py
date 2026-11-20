"""Helpers shared by every DarsAI module."""

from typing import List, Tuple

from telegram import Message

LANGUAGES = {
    "en": "English",
    "english": "English",
    "fa": "Persian/Farsi",
    "farsi": "Persian/Farsi",
    "persian": "Persian/Farsi",
    "de": "German",
    "german": "German",
    "it": "Italian",
    "italian": "Italian",
    "fr": "French",
    "french": "French",
    "es": "Spanish",
    "spanish": "Spanish",
    "ar": "Arabic",
    "arabic": "Arabic",
}


def extract_language(text: str, default: str = "English") -> Tuple[str, str]:
    """Split an optional leading language code off a command argument."""
    parts = (text or "").strip().split()
    if parts and parts[0].lower() in LANGUAGES:
        return " ".join(parts[1:]).strip(), LANGUAGES[parts[0].lower()]
    return (text or "").strip(), default


# Telegram allows 4096 characters per message (counted in UTF-16 units, so emoji
# can count double). Stay safely under it.
TELEGRAM_MESSAGE_LIMIT = 4000


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> List[str]:
    """Split text into Telegram-sized chunks, preferring line, then word, boundaries."""
    text = (text or "").strip()
    chunks: List[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


async def reply_long(message: Message, text: str) -> None:
    """Reply with text of any length, splitting it across several messages if needed."""
    chunks = split_message(text)
    if not chunks:
        chunks = ["I could not generate a response. Please try again."]
    for chunk in chunks:
        await message.reply_text(chunk)
