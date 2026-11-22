# DarsAI MVP

A scalable Telegram AI tutor MVP focused on math learning.

Requires Python 3.10 or newer (python-telegram-bot 22 does not support older versions).

## Run on Render
Start command:

```bash
uvicorn main:api --host 0.0.0.0 --port $PORT
```

## Environment variables

See `.env.example` for a full template.

```text
TELEGRAM_BOT_TOKEN=...                       required
WEBHOOK_URL=https://your-render-service.onrender.com   required
SECRET_PATH=darsai-webhook                   URL path Telegram posts updates to
TELEGRAM_WEBHOOK_SECRET=...                  optional; derived from the bot token if unset
AI_PROVIDER=groq                             groq | openrouter | openai
GROQ_API_KEY=...
AI_MODEL=qwen/qwen3.8-27b                    the default; must be a model your provider key can use
DATABASE_URL=postgresql://...                optional but recommended (memory, progress, limits survive restarts)
DB_POOL_MAX_SIZE=5
AI_MEMORY_ENABLED=true
FREE_DAILY_AI_LIMIT=30                       AI messages per user per UTC day; 0 = unlimited
```

The webhook only accepts requests that carry Telegram's `X-Telegram-Bot-Api-Secret-Token`
header. The bot registers that secret with Telegram on startup, so no extra setup is needed.

## Test locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -t .
```

The tests use in-memory storage and never call Telegram or an AI provider.

## Run locally with a test bot

`run_local.py` runs the same handlers with long polling, so you don't need a public URL.
Render keeps using `uvicorn main:api` with the webhook.

1. Create a separate test bot with @BotFather. Don't use the production token.
2. Create `.env.local` (git-ignored) in the project folder:

   ```text
   LOCAL_TELEGRAM_BOT_TOKEN=123456:your-test-bot-token
   GROQ_API_KEY=...
   # LOCAL_DATABASE_URL=postgresql://...   optional; empty = in-memory storage
   ```

3. Run `python run_local.py` and message your test bot. Press Ctrl+C to stop.

The script only reads `LOCAL_TELEGRAM_BOT_TOKEN` and `LOCAL_DATABASE_URL` and ignores
`TELEGRAM_BOT_TOKEN` and `DATABASE_URL`, so it can't reach the production bot or database. It also
refuses to start if the bot has a webhook set, because polling would delete the production webhook.

## Core commands

```text
/start
/math
/mathhelp
/level high_school
/lesson high_school quadratics
/math_tutor fa high_school quadratics explain the quadratic formula
/solve 2x + 5 = 17
/practice high_school algebra
/check 5
/plot y=x^2 range -5 5
/progress
/aihelp
/chat explain how to study algebra
```
