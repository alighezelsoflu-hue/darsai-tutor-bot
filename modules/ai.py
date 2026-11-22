import asyncio
import logging
import re
import threading
from datetime import date, datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import (
    AI_MAX_HISTORY_MESSAGES,
    AI_MEMORY_ENABLED,
    AI_MODEL,
    AI_PROVIDER,
    BOT_NAME,
    FREE_DAILY_AI_LIMIT,
    GROQ_API_KEY,
    OPENAI_API_KEY,
    OPENROUTER_API_KEY,
    WEBHOOK_URL,
)
from modules.common import extract_language, reply_long
from modules.db import connection, db_configured

logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# Database memory
# ------------------------------------------------------------
# All functions in this section are blocking. Call them with asyncio.to_thread.

_MEMORY_FALLBACK: Dict[Tuple[int, int, str], List[Dict[str, str]]] = {}
_TOPIC_PATTERN = re.compile(r"^[a-z0-9_]{1,40}$")
MAX_STORED_MESSAGE_CHARS = 8000


def normalize_topic(topic: str) -> str:
    topic = (topic or "general").strip().lower().replace(" ", "_").replace("-", "_")
    return topic if _TOPIC_PATTERN.match(topic) else "general"


def init_ai_db() -> None:
    if not db_configured():
        return
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS darsai_ai_messages (
                id BIGSERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                topic TEXT NOT NULL DEFAULT 'general',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_darsai_ai_messages_lookup
            ON darsai_ai_messages (chat_id, user_id, topic, id DESC);
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS darsai_ai_usage (
                user_id BIGINT NOT NULL,
                day DATE NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id, day)
            );
            """
        )


def load_history(chat_id: int, user_id: int, topic: str, limit: int = AI_MAX_HISTORY_MESSAGES) -> List[Dict[str, str]]:
    if not AI_MEMORY_ENABLED or limit <= 0:
        return []
    topic = normalize_topic(topic)
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content
                FROM darsai_ai_messages
                WHERE chat_id = %s AND user_id = %s AND topic = %s
                ORDER BY id DESC
                LIMIT %s;
                """,
                (chat_id, user_id, topic, limit),
            )
            rows = cur.fetchall()
        return [{"role": role, "content": content} for role, content in reversed(rows)]

    return list(_MEMORY_FALLBACK.get((chat_id, user_id, topic), [])[-limit:])


def save_exchange(chat_id: int, user_id: int, topic: str, user_text: str, assistant_text: str) -> None:
    """Store one user message and the tutor's answer in the topic's memory."""
    if not AI_MEMORY_ENABLED:
        return
    topic = normalize_topic(topic)
    messages = [
        (role, content.strip()[:MAX_STORED_MESSAGE_CHARS])
        for role, content in (("user", user_text or ""), ("assistant", assistant_text or ""))
        if content.strip()
    ]
    if not messages:
        return

    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO darsai_ai_messages (chat_id, user_id, topic, role, content)
                VALUES (%s, %s, %s, %s, %s);
                """,
                [(chat_id, user_id, topic, role, content) for role, content in messages],
            )
        return

    key = (chat_id, user_id, topic)
    history = _MEMORY_FALLBACK.setdefault(key, [])
    history.extend({"role": role, "content": content} for role, content in messages)
    _MEMORY_FALLBACK[key] = history[-50:]


def clear_history(chat_id: int, user_id: int, topics: Iterable[str] = ("general",), all_topics: bool = False) -> int:
    """Delete saved AI messages for the given topics (or every topic). Returns how many were deleted."""
    topic_list = sorted({normalize_topic(t) for t in topics})
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            if all_topics:
                cur.execute(
                    "DELETE FROM darsai_ai_messages WHERE chat_id = %s AND user_id = %s;",
                    (chat_id, user_id),
                )
            else:
                cur.execute(
                    "DELETE FROM darsai_ai_messages WHERE chat_id = %s AND user_id = %s AND topic = ANY(%s);",
                    (chat_id, user_id, topic_list),
                )
            return cur.rowcount

    deleted = 0
    for key in list(_MEMORY_FALLBACK.keys()):
        if key[0] == chat_id and key[1] == user_id and (all_topics or key[2] in topic_list):
            deleted += len(_MEMORY_FALLBACK.pop(key, []))
    return deleted


# ------------------------------------------------------------
# Daily AI usage limit
# ------------------------------------------------------------

class AILimitReached(Exception):
    pass


_USAGE_FALLBACK: Dict[Tuple[int, date], int] = {}
_usage_lock = threading.Lock()


def _today() -> date:
    return datetime.now(timezone.utc).date()


def reserve_ai_message(user_id: int) -> Optional[date]:
    """Count one AI message against today's limit.

    Returns the day that was charged (None when there is no limit), or raises
    AILimitReached when the user has no messages left today.
    """
    if FREE_DAILY_AI_LIMIT <= 0:
        return None
    day = _today()
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            # Atomic: only increments while the count is still under the limit.
            cur.execute(
                """
                INSERT INTO darsai_ai_usage (user_id, day, count)
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id, day)
                DO UPDATE SET count = darsai_ai_usage.count + 1
                WHERE darsai_ai_usage.count < %s
                RETURNING count;
                """,
                (user_id, day, FREE_DAILY_AI_LIMIT),
            )
            if cur.fetchone() is None:
                raise AILimitReached()
        return day

    with _usage_lock:
        for key in [k for k in _USAGE_FALLBACK if k[1] != day]:
            del _USAGE_FALLBACK[key]
        used = _USAGE_FALLBACK.get((user_id, day), 0)
        if used >= FREE_DAILY_AI_LIMIT:
            raise AILimitReached()
        _USAGE_FALLBACK[(user_id, day)] = used + 1
    return day


def release_ai_message(user_id: int, day: Optional[date]) -> None:
    """Give back a reserved message, e.g. when the AI provider failed."""
    if day is None:
        return
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE darsai_ai_usage SET count = GREATEST(count - 1, 0) WHERE user_id = %s AND day = %s;",
                (user_id, day),
            )
        return
    with _usage_lock:
        key = (user_id, day)
        if _USAGE_FALLBACK.get(key, 0) > 0:
            _USAGE_FALLBACK[key] -= 1


# ------------------------------------------------------------
# AI provider client
# ------------------------------------------------------------

class AIProviderError(RuntimeError):
    pass


def provider_config() -> Tuple[str, str, str, Dict[str, str]]:
    provider = AI_PROVIDER.lower().strip()
    model = AI_MODEL
    headers = {"Content-Type": "application/json"}

    if provider == "groq":
        if not GROQ_API_KEY:
            raise AIProviderError("GROQ_API_KEY is missing. Add it in Render environment variables.")
        return "groq", "https://api.groq.com/openai/v1/chat/completions", model, {
            **headers,
            "Authorization": f"Bearer {GROQ_API_KEY}",
        }

    if provider == "openrouter":
        if not OPENROUTER_API_KEY:
            raise AIProviderError("OPENROUTER_API_KEY is missing. Add it in Render environment variables.")
        return "openrouter", "https://openrouter.ai/api/v1/chat/completions", model, {
            **headers,
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": WEBHOOK_URL or "https://example.com",
            "X-Title": BOT_NAME,
        }

    if provider == "openai":
        if not OPENAI_API_KEY:
            raise AIProviderError("OPENAI_API_KEY is missing. Add it in Render environment variables.")
        return "openai", "https://api.openai.com/v1/chat/completions", model, {
            **headers,
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        }

    raise AIProviderError(f"Unsupported AI_PROVIDER: {AI_PROVIDER}")


async def call_ai_provider(
    messages: List[Dict[str, str]],
    max_tokens: int = 900,
    temperature: float = 0.25,
) -> str:
    _, url, model, headers = provider_config()
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as error:
        raise AIProviderError(f"Could not reach the AI provider: {error!r}") from error
    if response.status_code >= 400:
        raise AIProviderError(f"AI provider error {response.status_code}: {response.text[:500]}")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise AIProviderError(f"Unexpected AI provider response: {response.text[:500]}") from error
    return (content or "").strip()


async def ask_ai_with_memory(
    chat_id: int,
    user_id: int,
    topic: str,
    user_prompt: str,
    system_prompt: str,
    max_tokens: int = 900,
    temperature: float = 0.25,
) -> str:
    """Ask the AI with the student's saved history for this topic. Counts toward the daily limit."""
    topic = normalize_topic(topic)
    day = await asyncio.to_thread(reserve_ai_message, user_id)
    try:
        history = await asyncio.to_thread(load_history, chat_id, user_id, topic)
        messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_prompt}]
        answer = await call_ai_provider(messages, max_tokens=max_tokens, temperature=temperature)
    except Exception:
        await asyncio.to_thread(release_ai_message, user_id, day)
        raise
    try:
        await asyncio.to_thread(save_exchange, chat_id, user_id, topic, user_prompt, answer)
    except Exception:
        logger.exception("Could not save AI memory for topic %s", topic)
    return answer


def log_ai_error(error: Exception) -> None:
    """Log a failed AI request. A provider error is expected (no traceback); anything else is a bug."""
    logger.error("AI request failed: %s", error, exc_info=None if isinstance(error, AIProviderError) else error)


def ai_error_message(error: Exception) -> str:
    """User-facing text for a failed AI request. Details go to the log, not to the student."""
    if isinstance(error, AILimitReached):
        return (
            f"You have used all {FREE_DAILY_AI_LIMIT} free AI tutor messages for today. "
            "The limit resets at 00:00 UTC.\n\n"
            "You can still use /lesson, /practice, /solve and /plot."
        )
    log_ai_error(error)
    return "The AI tutor is not available right now. Please try again in a few minutes."


# ------------------------------------------------------------
# Tutor prompts
# ------------------------------------------------------------

GENERAL_TUTOR_PROMPT = (
    f"You are {BOT_NAME}, a specialized AI tutor for students. "
    "Do not behave like a generic chatbot. Teach step by step. "
    "First identify the student's goal, then explain the idea, then give an example, "
    "then ask a short follow-up question. Use encouraging language. "
    "If the student is wrong, diagnose the mistake kindly."
)


def ai_tools_text() -> str:
    limit_line = f"Free plan: {FREE_DAILY_AI_LIMIT} AI tutor messages per day.\n\n" if FREE_DAILY_AI_LIMIT > 0 else ""
    return (
        f"{BOT_NAME} AI tools 🤖\n\n"
        "/chat your message - continue a personal tutoring chat\n"
        "/askai your message - same as /chat\n"
        "/newchat - clear your current AI memory\n"
        "/newchat all - clear all your AI topics in this chat\n\n"
        f"{limit_line}"
        "Examples:\n"
        "/chat explain how to study math better\n"
        "/askai fa یک برنامه مطالعه ریاضی بده\n"
    )


async def aihelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧮 Math tutor", callback_data="menu:math")],
        [InlineKeyboardButton("🆕 Clear chat", callback_data="ai:newchat")],
    ])
    await update.message.reply_text(ai_tools_text(), reply_markup=keyboard)


async def chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.effective_chat:
        return
    text = " ".join(context.args or []).strip()
    if not text and update.message.reply_to_message:
        text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
    text, language = extract_language(text)
    if not text:
        await update.message.reply_text("Usage:\n/chat explain fractions\n/chat fa کسرها را توضیح بده")
        return
    await update.message.reply_text("Thinking like a tutor...")
    system = GENERAL_TUTOR_PROMPT + f" Respond in {language}."
    try:
        answer = await ask_ai_with_memory(
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            topic="general",
            user_prompt=text,
            system_prompt=system,
            max_tokens=900,
            temperature=0.25,
        )
    except Exception as error:
        await update.message.reply_text(ai_error_message(error))
        return
    await reply_long(update.message, answer)


async def newchat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.effective_chat:
        return
    all_topics = bool(context.args) and context.args[0].lower() == "all"
    deleted = await asyncio.to_thread(
        clear_history, update.effective_chat.id, update.effective_user.id, ("general",), all_topics
    )
    await update.message.reply_text(f"Cleared {deleted} saved AI messages." if deleted else "No saved AI messages to clear.")


async def ai_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user or not update.effective_chat:
        return
    await query.answer()
    if query.data == "ai:newchat":
        deleted = await asyncio.to_thread(
            clear_history, update.effective_chat.id, update.effective_user.id, ("general",)
        )
        await query.edit_message_text(f"Cleared {deleted} general AI messages." if deleted else "No general AI memory to clear.")


def register_ai_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("aihelp", aihelp_command))
    app.add_handler(CommandHandler("chat", chat_command))
    app.add_handler(CommandHandler("askai", chat_command))
    app.add_handler(CommandHandler("ai", chat_command))
    app.add_handler(CommandHandler("newchat", newchat_command))
