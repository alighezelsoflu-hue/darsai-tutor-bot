"""Test settings. Imported before any test module, so config.py sees these values."""

import os

os.environ["TELEGRAM_BOT_TOKEN"] = "123456:TEST_TOKEN"
os.environ["WEBHOOK_URL"] = "https://example.com"
os.environ["SECRET_PATH"] = "test-webhook"
os.environ["DATABASE_URL"] = ""  # use the in-memory fallbacks
os.environ["AI_MEMORY_ENABLED"] = "true"
os.environ["FREE_DAILY_AI_LIMIT"] = "3"
os.environ.pop("TELEGRAM_WEBHOOK_SECRET", None)
os.environ.pop("AI_MODEL", None)  # test the default model, not the one in your shell
