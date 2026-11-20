# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

DarsAI is a Telegram bot that tutors students in math. FastAPI receives Telegram webhook calls, python-telegram-bot handles the commands, an OpenAI-compatible LLM (Groq by default) does the tutoring, and an optional PostgreSQL database (Neon in production) stores memory, progress and usage. There is no web frontend. It needs Python 3.10 or newer.

Work happens on `develop`. PRs go to `main`, and Render deploys from `main`. There is no `render.yaml`, so the Render service settings exist only in the Render dashboard.

## Commands

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -t .                                          # all tests
python -m unittest tests.test_math_shared.SolverTests                               # one class
python -m unittest tests.test_math_shared.SolverTests.test_linear_and_quadratic     # one test
python run_local.py                                                                 # local bot, long polling
uvicorn main:api --host 0.0.0.0 --port $PORT                                        # Render start command
```

- Run tests as modules of the `tests` package. `tests/__init__.py` sets environment variables before `config.py` is imported: a fake bot token, an empty `DATABASE_URL` so the in-memory fallbacks are used, and `FREE_DAILY_AI_LIMIT=3`. The tests never call Telegram, an AI provider or a database.
- No linter or formatter is configured.
- `run_local.py` is local dev mode. It uses long polling with a separate BotFather test bot and reads `.env.local`, which is git-ignored. It takes the bot token only from `LOCAL_TELEGRAM_BOT_TOKEN` and the database only from `LOCAL_DATABASE_URL` (empty means in-memory). It sets a placeholder `WEBHOOK_URL` before importing `main`, because `main.py` raises an error at import time without one, and then reuses `main.telegram_app`. Its `post_init` refuses to start if the bot already has a webhook, because polling deletes the webhook and would take production offline. Keep this guard. Render never runs this file, so `main.py` stays webhook-only.
- To check handlers without Telegram, send real `Update` objects through `main.telegram_app` and mock `reply_text`, the callback-query methods and `ai.call_ai_provider`.
- All settings come from environment variables, which `config.py` reads at import time. `.env.example` lists every one of them.

## Architecture

```
Telegram ──POST /{SECRET_PATH} (secret header checked)──▶ main.py (FastAPI, lifespan)
   └─▶ update_queue ─▶ Application (concurrent_updates=True)
         ├─ main.py               /help /subscribe, old main: menu buttons, error handler, init_databases()
         ├─ modules/ui/           button interface: /start, main menu, Settings, typed text in private chats
         │     ├─ core.py         callback data (pack/unpack), owner check, Screen (show = edit or send)
         │     ├─ home.py         main menu and Settings screens
         │     └─ router.py       ROUTES: first part of a button's route → screen handler
         ├─ modules/i18n/         interface text: en.py and fa.py (same keys), t(), level_label()
         ├─ modules/student.py    per-student settings (language, level) in darsai_student
         ├─ modules/ai.py         /chat /askai /ai /aihelp /newchat; AI memory, daily limit, provider client
         └─ modules/math/math.py  /math /mathhelp /level /lesson /math_tutor /solve /practice /quiz /check /progress /math_newchat
               ├─ plot.py         /plot (Pillow PNG)
               ├─ shared.py       levels, profiles, progress, active questions, Expression parser, solver, answers_match, poly_text
               ├─ prompts.py      math tutor system prompt
               └─ <level>/<topic>.py   lesson() + practice() generators
modules/db.py      psycopg_pool connection pool (connection(), db_configured(), close_pool())
modules/common.py  LANGUAGES, extract_language(), split_message(), reply_long()
```

- **Webhook:** the webhook handler compares the `X-Telegram-Bot-Api-Secret-Token` header with `config.WEBHOOK_SECRET_TOKEN` and returns 403 if they don't match. The secret is `TELEGRAM_WEBHOOK_SECRET`, or a SHA-256 hash derived from the bot token if that is unset. The handler puts the update on `telegram_app.update_queue` and returns immediately, so a slow AI reply never holds the HTTP request open. `GET /` must not reveal the webhook path, and a test checks this.
- **Startup (`lifespan` in `main.py`):** creates the database tables with `init_databases()` (also used by `run_local.py`), starts the Application, sets the "/" menu (only /start and /help, in English and Persian), then calls `set_webhook` with the secret. Shutdown closes the database pool.
- **Button interface:** new buttons use callback data `d1:<owner user id>:<route>[:<arg>…]`, built with `Screen.button()` / `core.pack()` (Telegram's limit is 64 bytes). `router.callback_router` rejects presses by anyone but the owner with a pop-up, then dispatches on the first route part through `ROUTES`. Main menu entries without a route show "coming soon". Screens draw with `Screen.show()`, which edits the pressed message and falls back to sending a new one (e.g. when the message is a photo). Every `Screen` handler call ends with the button press answered.
- **Old buttons:** `main:` and `menu:` still go to `main.py`, `ai:` to `ai.py`, and `math_` to `math.py`, so buttons in old messages keep working.
- **Languages:** the interface language is the student's choice in Settings, or a guess from their Telegram language code. Keyboards are mirrored for Persian (`core.arrange`). Private chats also get a persistent 🏠 Menu reply keyboard; its label in either language opens the menu.
- **Storage:** every storage function has two branches. When `db_configured()` is true it uses PostgreSQL. Otherwise it uses a module-level dict: `_MEMORY_FALLBACK` and `_USAGE_FALLBACK` in `ai.py`, and `PROFILE_FALLBACK`, `PROGRESS_FALLBACK` and `ACTIVE_QUESTION_FALLBACK` in `shared.py`. Tests run against these dicts and clear them in `setUp`. The tables are `darsai_ai_messages`, `darsai_ai_usage`, `darsai_student`, `darsai_user_profile`, `darsai_math_progress` and `darsai_active_question`. Settings (language, level) are per student in `darsai_student` and follow them into every chat; `darsai_user_profile` is only read as a fallback for levels saved per chat before that. Progress and the active practice question are keyed by `(chat_id, user_id)`, so students in the same group chat don't share state.
- **AI calls:** `ask_ai_with_memory()` takes one message from the daily limit (`reserve_ai_message`, an atomic SQL upsert), loads the history for `(chat_id, user_id, topic)`, calls the provider, gives the message back if the call fails, and saves the exchange. Memory topics are `general` for `/chat`, `math` for the tutor answer from `/solve`, and the canonical topic name (such as `quadratics`) for `/math_tutor`. `provider_config()` picks the URL and API key for groq, openrouter or openai. All three use the OpenAI chat-completions format through `httpx`.
- **Math flow:** `TOPIC_MODULES` in `math.py` maps `(level, topic)` to a module that has `lesson()` and `practice()`, and `DEFAULT_TOPIC` gives each level's fallback topic. `/practice` saves the generated question with `save_active_question`. `/check` compares the student's answer with `answers_match()` and calls `record_progress`. `/solve` uses `solve_equation()`, which fits a polynomial through x = 0, 1, 2, checks the fit at five more points, and raises `UnsupportedEquation` for anything that isn't linear or quadratic.
- **Imports:** `modules/math/__init__.py` deliberately doesn't import `math.py`, so `shared.py` and the topic modules can be imported without python-telegram-bot.

## Conventions to keep

- Database functions are synchronous. Handlers must call them with `await asyncio.to_thread(fn, ...)`, never directly. Use `with connection() as conn, conn.cursor() as cur:`. The pool commits on success and rolls back on error.
- Tables are created once at startup (`init_ai_db` and `init_math_db` in `main.lifespan`), never per request.
- Every AI call goes through `ask_ai_with_memory()`, which charges the daily limit and refunds it if the call fails. Show users `ai_error_message(error)`, never the raw error.
- Send AI output with `reply_long()` so replies over 4000 characters are split.
- Math input goes through `Expression` / `safe_eval` (an AST whitelist). Never use `eval`.
- Topic memory keys are canonical topic names (`linear_equations`, `quadratics`, …). Add aliases to `TOPIC_ALIASES` and new topic modules to `TOPIC_MODULES` in `math.py`. `MATH_MEMORY_TOPICS` is derived from `TOPIC_MODULES`.
- New practice generators should format polynomials with `poly_text()` and return `{question, answer, topic, level, explanation}`. `answers_match()` compares answers by value.
- Text students see in the button interface comes from `modules/i18n/en.py` and `fa.py`, never inline strings. Add every key to both files with the same `{placeholders}` (a test checks this). Persian uses casual «تو», and the user reviews all Persian text. Put formulas on their own line instead of inside a Persian sentence.
- Keep the httpx logger at WARNING (set in `main.py`). Its INFO logs include request URLs, and Telegram URLs contain the bot token.

## Local environment gotchas

- The default `python` is Anaconda base 3.8 with no dependencies, so tests fail with `No module named 'fastapi'`. python-telegram-bot 22.7 needs Python 3.10+. Suggested setup: `conda create -n darsai python=3.11 -y && conda activate darsai && pip install -r requirements.txt`.
- A 3.11 interpreter exists at `/Users/ali/opt/anaconda3/envs/rota/bin/python`. That env belongs to another project, so use it only to create a separate venv and never install into it.
- PostgreSQL binaries for a throwaway test database are in `/Users/ali/opt/anaconda3/envs/rota-pgtools/bin/` (`initdb`, `pg_ctl`). Listen on 127.0.0.1 with a custom port, use `--auth=trust`, and delete the data directory afterwards.
- The `gh` CLI is not installed, so PRs can't be opened from the terminal until the user runs `brew install gh` and `gh auth login`. Until then, push and let the user open the PR on github.com. `git push` uses the macOS Keychain login. Always ask the user before pushing.

## Deploying

After a merge to `main`, Render redeploys. On startup the bot creates any missing tables and registers the webhook again with the secret. To check it, open `https://api.telegram.org/bot<TOKEN>/getWebhookInfo`: `last_error_message` should be empty. Don't paste the token anywhere public. In production, set `DATABASE_URL`, because the in-memory fallbacks belong to a single process and are lost on restart.
