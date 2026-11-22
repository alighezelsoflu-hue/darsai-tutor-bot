import hashlib
import os
import re
from typing import FrozenSet, List, Tuple

# Settings that had a value this code couldn't use, so the default was taken. Logged at startup (alerts.py),
# because a typo in a setting must never stop the bot.
SETTING_WARNINGS: List[str] = []


def _int_env(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name, "").strip().strip("\"'")
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        SETTING_WARNINGS.append(f"{name}={raw!r} isn't a whole number, so {default} is used.")
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().strip("\"'").lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    SETTING_WARNINGS.append(f"{name}={raw!r} isn't true or false, so {str(default).lower()} is used.")
    return default


# Telegram / hosting
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
SECRET_PATH = os.getenv("SECRET_PATH", "darsai-webhook").strip().strip("/")

# Telegram sends this value in the X-Telegram-Bot-Api-Secret-Token header on every
# webhook call, so the bot can reject requests that did not come from Telegram.
# If it is not set, a stable value is derived from the bot token.
_WEBHOOK_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


def _webhook_secret_token() -> str:
    configured = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if configured:
        if not _WEBHOOK_SECRET_PATTERN.match(configured):
            raise RuntimeError("TELEGRAM_WEBHOOK_SECRET may only contain A-Z, a-z, 0-9, _ and - (1-256 characters).")
        return configured
    if not TOKEN:
        return ""
    return hashlib.sha256(f"darsai-webhook-secret:{TOKEN}".encode()).hexdigest()


WEBHOOK_SECRET_TOKEN = _webhook_secret_token()

# Product
BOT_NAME = os.getenv("BOT_NAME", "DarsAI")


def parse_admin_ids(text: str) -> Tuple[FrozenSet[int], Tuple[str, ...]]:
    """Telegram user ids separated by commas or spaces, e.g. "123456789, 987654321".

    Never fails: quotes around a value are removed, and anything that still isn't a number is returned
    in the second item, so startup can log a warning instead of stopping the bot.
    """
    ids, ignored = set(), []
    for part in re.split(r"[\s,;]+", text or ""):
        part = part.strip("\"'`")
        if not part:
            continue
        if part.isdecimal():
            ids.add(int(part))
        else:
            ignored.append(part)
    return frozenset(ids), tuple(ignored)


# Who may use /stats and the other admin commands, and who gets the error alerts. Empty means nobody.
# modules/stats.py logs the parts it had to ignore.
ADMIN_USER_IDS, ADMIN_USER_IDS_IGNORED = parse_admin_ids(os.getenv("ADMIN_USER_IDS", ""))

# Error alerts (modules/alerts.py): every ERROR in the log goes to the admins on Telegram, the same kind of
# error at most once per ALERT_REPEAT_MINUTES. Sentry is used too when SENTRY_DSN is set.
ALERTS_TO_ADMINS = _bool_env("ALERTS_TO_ADMINS", True)
ALERT_REPEAT_MINUTES = _int_env("ALERT_REPEAT_MINUTES", 30, minimum=1)
SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
SENTRY_ENVIRONMENT = os.getenv("SENTRY_ENVIRONMENT", "").strip() or "production"

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "5"))
AI_MEMORY_ENABLED = os.getenv("AI_MEMORY_ENABLED", "true").lower() in {"1", "true", "yes", "on"}

# AI provider
AI_PROVIDER = os.getenv("AI_PROVIDER", "groq").lower().strip()
# Groq removed llama-3.1-8b-instant. qwen/qwen3.8-27b gave the best casual Persian and plain text.
DEFAULT_AI_MODEL = "qwen/qwen3.8-27b"
AI_MODEL = os.getenv("AI_MODEL", "").strip() or DEFAULT_AI_MODEL
AI_MAX_HISTORY_MESSAGES = int(os.getenv("AI_MAX_HISTORY_MESSAGES", "16"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

# Subscription MVP settings: AI messages per user per UTC day. 0 or less means unlimited.
FREE_DAILY_AI_LIMIT = int(os.getenv("FREE_DAILY_AI_LIMIT", "30"))
