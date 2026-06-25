import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import (
    AI_MAX_HISTORY_MESSAGES,
    AI_MEMORY_ENABLED,
    AI_MODEL,
    AI_PROVIDER,
    BOT_NAME,
    DATABASE_URL,
    FREE_DAILY_AI_LIMIT,
    GROQ_API_KEY,
    OPENAI_API_KEY,
    OPENROUTER_API_KEY,
)

try:
    import psycopg
except Exception:  # pragma: no cover - local env may not have psycopg until install
    psycopg = None


# ------------------------------------------------------------
# Language helpers
# ------------------------------------------------------------

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
    parts = text.strip().split()
    if parts and parts[0].lower() in LANGUAGES:
        return " ".join(parts[1:]).strip(), LANGUAGES[parts[0].lower()]
    return text.strip(), default


# ------------------------------------------------------------
# Database memory
# ------------------------------------------------------------

_MEMORY_FALLBACK: Dict[Tuple[int, int, str], List[Dict[str, str]]] = {}


def db_available() -> bool:
    return bool(DATABASE_URL and psycopg and AI_MEMORY_ENABLED)


def get_conn():
    if not db_available():
        return None
    return psycopg.connect(DATABASE_URL)


def init_ai_db() -> None:
    if not db_available():
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
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
        conn.commit()


def load_history(chat_id: int, user_id: int, topic: str, limit: int = AI_MAX_HISTORY_MESSAGES) -> List[Dict[str, str]]:
    topic = normalize_topic(topic)
    if db_available():
        with get_conn() as conn:
            with conn.cursor() as cur:
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

    return _MEMORY_FALLBACK.get((chat_id, user_id, topic), [])[-limit:]


def save_message(chat_id: int, user_id: int, topic: str, role: str, content: str) -> None:
    topic = normalize_topic(topic)
    content = (content or "").strip()
    if not content:
        return

    if db_available():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO darsai_ai_messages (chat_id, user_id, topic, role, content)
                    VALUES (%s, %s, %s, %s, %s);
                    """,
                    (chat_id, user_id, topic, role, content[:8000]),
                )
            conn.commit()
        return

    key = (chat_id, user_id, topic)
    _MEMORY_FALLBACK.setdefault(key, []).append({"role": role, "content": content[:8000]})
    _MEMORY_FALLBACK[key] = _MEMORY_FALLBACK[key][-50:]


def clear_history(chat_id: int, user_id: int, topic: str = "general", all_topics: bool = False) -> int:
    topic = normalize_topic(topic)
    if db_available():
        with get_conn() as conn:
            with conn.cursor() as cur:
                if all_topics:
                    cur.execute(
                        "DELETE FROM darsai_ai_messages WHERE chat_id = %s AND user_id = %s;",
                        (chat_id, user_id),
                    )
                else:
                    cur.execute(
                        "DELETE FROM darsai_ai_messages WHERE chat_id = %s AND user_id = %s AND topic = %s;",
                        (chat_id, user_id, topic),
                    )
                deleted = cur.rowcount
            conn.commit()
        return deleted

    deleted = 0
    if all_topics:
        for key in list(_MEMORY_FALLBACK.keys()):
            if key[0] == chat_id and key[1] == user_id:
                deleted += len(_MEMORY_FALLBACK.pop(key, []))
    else:
        key = (chat_id, user_id, topic)
        deleted = len(_MEMORY_FALLBACK.pop(key, []))
    return deleted


def normalize_topic(topic: str) -> str:
    topic = (topic or "general").lower().strip().replace(" ", "_")
    allowed = {
        "general",
        "math",
        "middle_school",
        "high_school",
        "pre_college",
        "university",
        "algebra",
        "quadratics",
        "calculus",
        "plot",
    }
    return topic if topic in allowed else "general"


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
            "HTTP-Referer": os.getenv("WEBHOOK_URL", "https://example.com"),
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
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers=headers, json=payload)
    if response.status_code >= 400:
        raise AIProviderError(f"AI provider error {response.status_code}: {response.text[:500]}")
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


async def ask_ai(
    user_prompt: str,
    system_prompt: str = "You are a helpful assistant.",
    max_tokens: int = 900,
    temperature: float = 0.25,
) -> str:
    return await call_ai_provider(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )


async def ask_ai_with_memory(
    chat_id: int,
    user_id: int,
    topic: str,
    user_prompt: str,
    system_prompt: str,
    max_tokens: int = 900,
    temperature: float = 0.25,
) -> str:
    topic = normalize_topic(topic)
    history = load_history(chat_id, user_id, topic)
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_prompt}]
    answer = await call_ai_provider(messages, max_tokens=max_tokens, temperature=temperature)
    save_message(chat_id, user_id, topic, "user", user_prompt)
    save_message(chat_id, user_id, topic, "assistant", answer)
    return answer


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
    return (
        f"{BOT_NAME} AI tools 🤖\n\n"
        "/chat your message - continue a personal tutoring chat\n"
        "/askai your message - same as /chat\n"
        "/newchat - clear your current AI memory\n"
        "/newchat all - clear all your AI topics in this chat\n\n"
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
    text = " ".join(context.args).strip()
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
        await update.message.reply_text(f"AI error: {error}")
        return
    await update.message.reply_text(answer)


async def newchat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.effective_chat:
        return
    all_topics = context.args and context.args[0].lower() == "all"
    deleted = clear_history(update.effective_chat.id, update.effective_user.id, "general", all_topics=all_topics)
    await update.message.reply_text(f"Cleared {deleted} saved AI messages." if deleted else "No saved AI messages to clear.")


async def ai_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user or not update.effective_chat:
        return
    await query.answer()
    if query.data == "ai:newchat":
        deleted = clear_history(update.effective_chat.id, update.effective_user.id, "general", all_topics=False)
        await query.edit_message_text(f"Cleared {deleted} general AI messages." if deleted else "No general AI memory to clear.")


def register_ai_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("aihelp", aihelp_command))
    app.add_handler(CommandHandler("chat", chat_command))
    app.add_handler(CommandHandler("askai", chat_command))
    app.add_handler(CommandHandler("ai", chat_command))
    app.add_handler(CommandHandler("newchat", newchat_command))
