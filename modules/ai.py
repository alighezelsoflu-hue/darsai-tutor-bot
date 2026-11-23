import asyncio
import logging
import math
import re
import threading
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes

import config
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
from modules.alerts import BurstCounter
from modules.common import PLAIN_TEXT_RULE, extract_language, reply_long
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


# How many tokens a text costs, estimated on the safe side: the provider's tokenizer is unknown here (it differs by
# model), and an estimate that counts too few would send more than AI_HISTORY_TOKEN_BUDGET. Letters other than
# English ones (Persian) are half a token each; English letters and spaces a third; digits (Qwen splits numbers into
# single digits), punctuation, math symbols, emoji and the Persian half-space (ZWNJ) a whole token each; plus
# MESSAGE_TOKENS for each message's place in the chat format. ask_ai_with_memory logs the provider's real count next
# to this estimate, so it can be checked.
MESSAGE_TOKENS = 4


def estimate_tokens(text: str) -> int:
    halves = thirds = wholes = 0
    for char in text or "":
        if char.isdigit() or not (char.isalpha() or char.isspace()):
            wholes += 1
        elif char.isascii():
            thirds += 1
        else:
            halves += 1
    return math.ceil(halves / 2 + thirds / 3) + wholes + MESSAGE_TOKENS


def fit_history(history: List[Dict[str, str]], budget: int) -> List[Dict[str, str]]:
    """The newest whole question-and-answer pairs of the history whose estimated tokens fit the budget, oldest first.

    Stops at the first pair that doesn't fit (an older, shorter one would leave a gap in the conversation).
    """
    pairs: List[Tuple[Dict[str, str], Dict[str, str]]] = []
    used, index = 0, len(history) - 1
    while index >= 1:
        question, answer = history[index - 1], history[index]
        if question.get("role") != "user" or answer.get("role") != "assistant":
            index -= 1  # a message without its other half: never sent
            continue
        cost = estimate_tokens(question.get("content", "")) + estimate_tokens(answer.get("content", ""))
        if used + cost > budget:
            break
        pairs.append((question, answer))
        used += cost
        index -= 2
    return [message for pair in reversed(pairs) for message in pair]


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


def reserve_ai_message(user_id: int) -> date:
    """Count one AI message for today. Raises AILimitReached when the user has no messages left today.

    Messages are counted even with no limit (FREE_DAILY_AI_LIMIT 0 or less), because /stats reports them.
    Returns the day that was charged.
    """
    limit = FREE_DAILY_AI_LIMIT
    day = _today()
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            # Atomic: only increments while the count is still under the limit (or there is no limit).
            cur.execute(
                """
                INSERT INTO darsai_ai_usage (user_id, day, count)
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id, day)
                DO UPDATE SET count = darsai_ai_usage.count + 1
                WHERE %s <= 0 OR darsai_ai_usage.count < %s
                RETURNING count;
                """,
                (user_id, day, limit, limit),
            )
            if cur.fetchone() is None:
                raise AILimitReached()
        return day

    with _usage_lock:
        for key in [k for k in _USAGE_FALLBACK if k[1] != day]:
            del _USAGE_FALLBACK[key]
        used = _USAGE_FALLBACK.get((user_id, day), 0)
        if 0 < limit <= used:
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


class AIModelUnavailable(AIProviderError):
    """The provider no longer offers AI_MODEL (or the key can't use it). Only a config change fixes it."""


class AIBusy(AIProviderError):
    """The provider is limiting us (429), or every call slot stayed taken: the student hears "the tutor is busy",
    and the daily message is given back like for any failed call."""


class AIQuestionTooLong(Exception):
    """A question longer than AI_MAX_QUESTION_CHARS: refused before it counts or is sent anywhere."""

    def __init__(self, length: int, limit: int) -> None:
        super().__init__(f"The question has {length} characters (at most {limit}).")
        self.length, self.limit = length, limit


# Error codes providers return when the model is gone (Groq uses both, OpenAI the first).
MODEL_GONE_CODES = ("model_not_found", "model_decommissioned")

# Reasoning models put their hidden thinking in the answer between these tags.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN = re.compile(r"<think>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</think>", re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Remove the model's hidden reasoning (<think>…</think>) from an answer."""
    text = _THINK_BLOCK.sub("", text or "")
    # Only a closing tag left: the chat template opened the block, so the text starts mid-reasoning.
    text = _THINK_CLOSE.split(text)[-1]
    # Only an opening tag left: max_tokens cut the answer off while the model was still reasoning.
    text = _THINK_OPEN.split(text)[0]
    return text.strip()


def _error_code(response: httpx.Response) -> str:
    try:
        error = response.json().get("error") or {}
        return str(error.get("code") or "") if isinstance(error, dict) else ""
    except (ValueError, AttributeError):
        return ""


def provider_config(provider: Optional[str] = None, model: Optional[str] = None) -> Tuple[str, str, str, Dict[str, str]]:
    """(provider, URL, model, headers) for the main provider (AI_PROVIDER, AI_MODEL), or for the one given."""
    provider = (provider or AI_PROVIDER).lower().strip()
    model = model or AI_MODEL
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

    raise AIProviderError(f"Unsupported AI_PROVIDER: {provider}")


# ------------------------------------------------------------
# AI capacity: one shared HTTP client, call slots, "too many requests", the backup provider
# ------------------------------------------------------------

CONNECT_TIMEOUT_SECONDS = 5
ANSWER_TIMEOUT_SECONDS = 45  # and never past the question's deadline (AI_DEADLINE_SECONDS)
BACKUP_RESERVE_SECONDS = 15  # of the deadline, kept for the backup provider when there is one
MIN_CALL_SECONDS = 5  # less time than this left: don't start another call
TYPING_REPEAT_SECONDS = 4  # Telegram shows "typing…" for about 5 s

_http_client: Optional[httpx.AsyncClient] = None


def _new_http_client(transport: Optional[httpx.AsyncBaseTransport] = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(ANSWER_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=30),
        transport=transport,
    )


async def open_http_client(transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
    """At startup (main.lifespan, run_local.py): one connection pool for every AI call, kept open between calls."""
    global _http_client
    if _http_client is None:
        _http_client = _new_http_client(transport)


async def close_http_client() -> None:
    """At shutdown."""
    global _http_client
    client, _http_client = _http_client, None
    if client is not None:
        await client.aclose()


@asynccontextmanager
async def _client():
    if _http_client is not None:
        yield _http_client
    else:
        # Not opened (tests, scripts): a client for this call only.
        async with _new_http_client() as client:
            yield client


busy_events = BurstCounter("AI_BUSY_ALERT_THRESHOLD", "AI_BUSY_ALERT_WINDOW_MINUTES")


def note_busy(reason: str) -> None:
    """A "too many requests" from a provider, or a question that found no free slot: one WARNING (no alert). As many
    as AI_BUSY_ALERT_THRESHOLD within AI_BUSY_ALERT_WINDOW_MINUTES are one ERROR, so one alert."""
    count, alarm = busy_events.note()
    minutes = busy_events.window_minutes
    logger.warning("AI capacity: %s (%d in the last %d min)", reason, count, minutes)
    if alarm:
        logger.error(
            "AI capacity: %d refusals in the last %d min (last: %s). The provider's limits are full: time for its "
            "paid tier, or a backup provider (AI_FALLBACK_PROVIDER).", count, minutes, reason,
        )


class CallSlots:
    """At most AI_MAX_CONCURRENT_CALLS AI calls at once in this process. A semaphore belongs to one event loop, so a
    new loop (tests) or a changed setting gets a new one."""

    def __init__(self) -> None:
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._size = 0

    def _get(self) -> asyncio.Semaphore:
        loop, size = asyncio.get_running_loop(), config.AI_MAX_CONCURRENT_CALLS
        if self._semaphore is None or self._loop is not loop or self._size != size:
            self._semaphore, self._loop, self._size = asyncio.Semaphore(size), loop, size
        return self._semaphore

    @asynccontextmanager
    async def slot(self, wait_seconds: float):
        """Hold one slot, waiting at most wait_seconds for it; else AIBusy."""
        semaphore = self._get()
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=max(0.0, wait_seconds))
        except asyncio.TimeoutError:
            reason = f"all {self._size} AI call slots stayed taken for {max(0.0, wait_seconds):.0f} s"
            note_busy(reason)
            raise AIBusy(reason) from None
        try:
            yield
        finally:
            semaphore.release()


call_slots = CallSlots()

_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_DURATION_UNITS = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}


def _seconds(value: Optional[str]) -> Optional[float]:
    """A wait in seconds from "7", "7.5", "7.66s", "2m59.56s", "1h2m" or "300ms" (Groq's formats); else None."""
    value = (value or "").strip().lower()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    parts = _DURATION_PART.findall(value)
    if not parts or "".join(number + unit for number, unit in parts) != value:
        return None
    return sum(float(number) * _DURATION_UNITS[unit] for number, unit in parts)


def retry_wait(response: httpx.Response) -> Optional[float]:
    """How long a 429 asks us to wait: retry-after, else the reset time of the limit that is used up (Groq's
    x-ratelimit-* headers). None when it doesn't say."""
    wait = _seconds(response.headers.get("retry-after"))
    if wait is not None:
        return wait
    waits = [
        _seconds(response.headers.get(f"x-ratelimit-reset-{kind}"))
        for kind in ("requests", "tokens")
        if response.headers.get(f"x-ratelimit-remaining-{kind}", "").strip() == "0"
    ]
    waits = [wait for wait in waits if wait is not None]
    return max(waits) if waits else None


class _CallFailed(Exception):
    """One provider call failed. kind says whether the backup may help; error is what the caller gets."""

    def __init__(self, kind: str, error: AIProviderError, wait: Optional[float] = None) -> None:
        super().__init__(str(error))
        self.kind, self.error, self.wait = kind, error, wait


# Failures the backup provider may not share. Not a bad request (400, 413, 422 …) or an unreadable answer: the
# backup would most likely fail the same way.
FALLBACK_KINDS = frozenset({"rate_limit", "server", "timeout", "network", "auth", "model_gone"})
# Failures that need someone to fix a setting: an ERROR (an alert) even when the backup answered.
CONFIG_KINDS = frozenset({"auth", "model_gone"})


async def _post_once(
    target: Tuple[str, str, str, Dict[str, str]], messages: List[Dict[str, str]], max_tokens: int,
    temperature: float, timeout: float, model_setting: str,
) -> str:
    provider, url, model, headers = target
    payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    try:
        async with _client() as client:
            response = await asyncio.wait_for(client.post(url, headers=headers, json=payload), timeout=timeout)
    except (asyncio.TimeoutError, httpx.TimeoutException) as error:
        raise _CallFailed("timeout", AIProviderError(f"{provider} didn't answer within {timeout:.0f} s")) from error
    except httpx.HTTPError as error:
        raise _CallFailed("network", AIProviderError(f"Could not reach the AI provider ({provider}): {error!r}")) from error
    status = response.status_code
    if status >= 400:
        code = _error_code(response)
        if code in MODEL_GONE_CODES:
            raise _CallFailed("model_gone", AIModelUnavailable(
                f"{model_setting} {model!r} is no longer available from {provider} ({code}). The tutor is down "
                f"until {model_setting} is set to a model this API key can use (Render: Environment)."
            ))
        if status == 429:
            wait = retry_wait(response)
            after = f", retry in {wait:g} s" if wait is not None else ""
            raise _CallFailed("rate_limit", AIBusy(f"{provider} rate limit (429{after})"), wait)
        kind = "auth" if status in (401, 403) else "server" if status >= 500 or status == 408 else "request"
        raise _CallFailed(kind, AIProviderError(f"AI provider error {status} from {provider}: {response.text[:500]}"))
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise _CallFailed("response", AIProviderError(f"Unexpected AI provider response: {response.text[:500]}")) from error
    answer = strip_reasoning(content)
    if not answer:
        # Nothing but reasoning (or nothing at all). Failing gives the student's daily message back.
        raise _CallFailed("response", AIProviderError(
            f"The AI answer was empty after removing reasoning ({len(content or '')} characters)."
        ))
    usage = body.get("usage") if isinstance(body, dict) else None
    counted = usage.get("prompt_tokens") if isinstance(usage, dict) else None
    # The estimate next to the provider's own count, to check that it stays on the safe side. No user ids.
    logger.info("AI answer from %s (%s): %s prompt tokens counted by the provider, %d estimated.", provider, model,
                counted if counted is not None else "?", sum(estimate_tokens(m.get("content", "")) for m in messages))
    return answer


async def _main_answer(messages, max_tokens, temperature, deadline: float, reserve: float) -> str:
    """The main provider, tried once more when a "too many requests" asks for a short wait."""
    loop = asyncio.get_running_loop()
    try:
        target = provider_config()
    except AIProviderError as error:  # no key, or an unknown AI_PROVIDER
        raise _CallFailed("auth", error) from None
    for attempt in (1, 2):
        left = deadline - loop.time()
        timeout = left - reserve if left - reserve >= MIN_CALL_SECONDS else left
        if timeout <= 0:
            raise _CallFailed("timeout", AIProviderError("No time left for the AI provider."))
        try:
            return await _post_once(target, messages, max_tokens, temperature, timeout, "AI_MODEL")
        except _CallFailed as failure:
            if failure.kind != "rate_limit":
                raise
            note_busy(str(failure.error))
            wait = failure.wait
            if (attempt == 2 or wait is None or wait > config.AI_RETRY_MAX_WAIT_SECONDS
                    or loop.time() + wait + MIN_CALL_SECONDS > deadline - reserve):
                raise
            await asyncio.sleep(wait)
    raise AssertionError("unreachable")


async def call_ai_provider(
    messages: List[Dict[str, str]],
    max_tokens: int = 900,
    temperature: float = 0.25,
    deadline: Optional[float] = None,
) -> str:
    """One answer before the deadline (the event loop's time; default AI_DEADLINE_SECONDS from now).

    The main provider first, once more after a short "too many requests"; then, after a failure the backup may not
    share (FALLBACK_KINDS), once the backup provider (AI_FALLBACK_PROVIDER) with the time that is left. Raises
    AIBusy (rate limited), AIModelUnavailable or AIProviderError, always the main provider's error.
    """
    loop = asyncio.get_running_loop()
    if deadline is None:
        deadline = loop.time() + config.AI_DEADLINE_SECONDS
    backup = config.AI_FALLBACK_PROVIDER
    try:
        return await _main_answer(messages, max_tokens, temperature, deadline, BACKUP_RESERVE_SECONDS if backup else 0)
    except _CallFailed as failure:
        main_failure = failure
    if not backup or main_failure.kind not in FALLBACK_KINDS or deadline - loop.time() < MIN_CALL_SECONDS:
        raise main_failure.error
    try:
        target = provider_config(backup, config.AI_FALLBACK_MODEL)
        answer = await _post_once(target, messages, max_tokens, temperature, deadline - loop.time(), "AI_FALLBACK_MODEL")
    except (_CallFailed, AIProviderError) as failure:
        kind, error = (failure.kind, failure.error) if isinstance(failure, _CallFailed) else ("auth", failure)
        if kind == "rate_limit":
            note_busy(f"the backup's {error}")
        # The student gets the main provider's error (logged by log_ai_error); a broken backup setting is an alert.
        logger.log(logging.ERROR if kind in CONFIG_KINDS else logging.WARNING,
                   "The backup AI (%s) failed too: %s", backup, error)
        raise main_failure.error from None
    logger.log(logging.ERROR if main_failure.kind in CONFIG_KINDS else logging.WARNING,
               "The main AI failed (%s), so the backup (%s) answered.", main_failure.error, backup)
    return answer


async def _keep_typing(send: Callable[[], Awaitable[Any]]) -> None:
    """Show "typing…" until the answer is there (Telegram shows it for about 5 s per call)."""
    while True:
        with suppress(Exception):
            await send()
        await asyncio.sleep(TYPING_REPEAT_SECONDS)


async def ask_ai_with_memory(
    chat_id: int,
    user_id: int,
    topic: str,
    user_prompt: str,
    system_prompt: str,
    max_tokens: int = 900,
    temperature: float = 0.25,
    typing: Optional[Callable[[], Awaitable[Any]]] = None,
) -> str:
    """Ask the AI with the student's saved history for this topic. Counts toward the daily limit.

    Refuses a question longer than AI_MAX_QUESTION_CHARS first (AIQuestionTooLong, nothing counted). Then the whole
    call, the wait for a free slot included, ends by AI_DEADLINE_SECONDS; a failure gives the daily message back.
    typing, when given, sends Telegram's "typing…" action; it is repeated until the answer is there.
    """
    if len(user_prompt) > config.AI_MAX_QUESTION_CHARS:
        raise AIQuestionTooLong(len(user_prompt), config.AI_MAX_QUESTION_CHARS)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + config.AI_DEADLINE_SECONDS
    topic = normalize_topic(topic)
    day = await asyncio.to_thread(reserve_ai_message, user_id)
    typing_task = asyncio.ensure_future(_keep_typing(typing)) if typing else None
    try:
        history = fit_history(await asyncio.to_thread(load_history, chat_id, user_id, topic), config.AI_HISTORY_TOKEN_BUDGET)
        messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_prompt}]
        async with call_slots.slot(min(config.AI_QUEUE_WAIT_SECONDS, deadline - loop.time())):
            answer = await call_ai_provider(messages, max_tokens=max_tokens, temperature=temperature, deadline=deadline)
    except BaseException:
        await asyncio.to_thread(release_ai_message, user_id, day)
        raise
    finally:
        if typing_task is not None:
            typing_task.cancel()
            with suppress(asyncio.CancelledError):
                await typing_task
    try:
        await asyncio.to_thread(save_exchange, chat_id, user_id, topic, user_prompt, answer)
    except Exception:
        logger.exception("Could not save AI memory for topic %s", topic)
    return answer


def chat_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> Callable[[], Awaitable[Any]]:
    """For the old commands: send "typing…" to this chat (ask_ai_with_memory's typing)."""
    return lambda: context.bot.send_chat_action(chat_id, ChatAction.TYPING)


def log_ai_error(error: Exception) -> None:
    """Log a failed AI request. A provider error is expected (no traceback); anything else is a bug.

    A busy tutor was logged where it happened (note_busy, a WARNING, no alert), and a question that was too long
    is the student's input, not a failure.
    """
    if isinstance(error, AIQuestionTooLong):
        return
    if isinstance(error, AIBusy):
        logger.info("Told a student the tutor is busy: %s", error)
        return
    logger.error("AI request failed: %s", error, exc_info=None if isinstance(error, AIProviderError) else error)


def ai_error_message(error: Exception) -> str:
    """User-facing text for a failed AI request (the old English commands). Details go to the log."""
    if isinstance(error, AILimitReached):
        return (
            f"You have used all {FREE_DAILY_AI_LIMIT} free AI tutor messages for today. "
            "The limit resets at 00:00 UTC.\n\n"
            "You can still use /lesson, /practice, /solve and /plot.\n\n"
            "💎 Premium, with more tutor messages, is coming. Send /subscribe to see it and tell me what you'd want most."
        )
    if isinstance(error, AIQuestionTooLong):
        return f"✂️ That question is too long ({error.length} characters). Please shorten it to at most {error.limit} characters."
    log_ai_error(error)
    if isinstance(error, AIBusy):
        return "⏳ The tutor is very busy right now. Please ask again in a minute. This one didn't count toward today's messages."
    return "The AI tutor is not available right now. Please try again in a few minutes."


# ------------------------------------------------------------
# Tutor prompts
# ------------------------------------------------------------

GENERAL_TUTOR_PROMPT = (
    f"You are {BOT_NAME}, a specialized AI tutor for students. "
    "Do not behave like a generic chatbot. Teach step by step. "
    "First identify the student's goal, then explain the idea, then give an example, "
    "then ask a short follow-up question. Use encouraging language. "
    "If the student is wrong, diagnose the mistake kindly. "
    + PLAIN_TEXT_RULE
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
            typing=chat_typing(context, update.effective_chat.id),
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
