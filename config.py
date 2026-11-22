import hashlib
import os
import re

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


def parse_admin_ids(text: str) -> frozenset:
    """Telegram user ids separated by commas or spaces, e.g. "123456789, 987654321"."""
    ids = set()
    for part in re.split(r"[\s,]+", (text or "").strip()):
        if not part:
            continue
        if not part.isdigit():
            raise RuntimeError(f"ADMIN_USER_IDS must be Telegram user ids (numbers) separated by commas, not {part!r}.")
        ids.add(int(part))
    return frozenset(ids)


# Who may use /stats. Empty means nobody.
ADMIN_USER_IDS = parse_admin_ids(os.getenv("ADMIN_USER_IDS", ""))

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
