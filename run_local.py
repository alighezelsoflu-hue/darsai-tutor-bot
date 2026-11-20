"""Run DarsAI on your laptop with long polling and a separate test bot.

Production (Render) runs `uvicorn main:api` with a webhook and never uses this file.

Setup:
  1. Create a test bot with @BotFather and copy its token.
  2. Put it in .env.local (git-ignored) next to this file:
         LOCAL_TELEGRAM_BOT_TOKEN=123456:your-test-bot-token
         GROQ_API_KEY=...
  3. python run_local.py

Only LOCAL_TELEGRAM_BOT_TOKEN is used as the bot token, and only LOCAL_DATABASE_URL as the
database (leave it empty to keep everything in memory), so a copied production .env cannot
make this script talk to the production bot or write to the production database.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

ENV_FILE = Path(__file__).resolve().with_name(".env.local")
# main.py requires WEBHOOK_URL at import time. Polling never uses it.
PLACEHOLDER_WEBHOOK_URL = "http://localhost"

logger = logging.getLogger("darsai.local")


class ProductionBotError(RuntimeError):
    """The token belongs to a bot that already has a webhook, most likely the production bot."""


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ. Variables already set in the shell win."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def prepare_environment() -> None:
    """Point config.py at the test bot and the local database before it is imported."""
    load_env_file(ENV_FILE)
    token = os.environ.get("LOCAL_TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        sys.exit(
            "LOCAL_TELEGRAM_BOT_TOKEN is not set.\n"
            "Create a test bot with @BotFather and add this line to .env.local:\n"
            "    LOCAL_TELEGRAM_BOT_TOKEN=123456:your-test-bot-token"
        )
    os.environ["TELEGRAM_BOT_TOKEN"] = token
    os.environ["DATABASE_URL"] = os.environ.get("LOCAL_DATABASE_URL", "").strip()
    os.environ["WEBHOOK_URL"] = PLACEHOLDER_WEBHOOK_URL


async def ensure_not_production(bot) -> None:
    """Polling deletes the bot's webhook. Refuse if one is set, so production is never taken offline."""
    info = await bot.get_webhook_info()
    if info.url:
        raise ProductionBotError(
            "This bot has a webhook set, so it is probably your production bot.\n"
            "Starting polling would delete that webhook and take the live bot offline.\n"
            "Use a separate test bot from @BotFather in LOCAL_TELEGRAM_BOT_TOKEN.\n"
            "If this really is a test bot, remove its webhook first by opening\n"
            "https://api.telegram.org/bot<TEST_TOKEN>/deleteWebhook in a browser."
        )


def main() -> None:
    if sys.version_info < (3, 10):
        sys.exit("DarsAI needs Python 3.10 or newer (python-telegram-bot 22). See README.md.")
    prepare_environment()

    # Imported only now, because config.py reads the environment at import time.
    from telegram import Update

    from main import setup_bot_commands, telegram_app
    from modules.ai import init_ai_db
    from modules.db import close_pool, db_configured
    from modules.math.shared import init_math_db

    async def post_init(app) -> None:
        await ensure_not_production(app.bot)
        await asyncio.to_thread(init_ai_db)
        await asyncio.to_thread(init_math_db)
        await setup_bot_commands()
        storage = "PostgreSQL (LOCAL_DATABASE_URL)" if db_configured() else "in-memory (lost on exit)"
        logger.info("Polling as @%s. Storage: %s. Press Ctrl+C to stop.", app.bot.username, storage)

    async def post_shutdown(app) -> None:
        await asyncio.to_thread(close_pool)

    telegram_app.post_init = post_init
    telegram_app.post_shutdown = post_shutdown
    try:
        telegram_app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except ProductionBotError as error:
        sys.exit(f"Refusing to start.\n{error}")


if __name__ == "__main__":
    main()
