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
         ├─ modules/ui/           button interface: /start, main menu and every screen behind it
         │     ├─ core.py         callback data (pack/unpack), owner check, Screen (show = edit or send, send_long, send_photo)
         │     ├─ home.py         main menu and Settings screens
         │     ├─ practice.py     ✍️ Practice: topics, questions, answers, retry, mastery text, formulas()
         │     ├─ learn.py        📘 Learn: lessons (also /lesson)
         │     ├─ tools.py        🧑‍🏫 Ask the tutor, 🧮 Solve, 📈 Plot (typed input modes)
         │     ├─ progress.py     📊 My progress
         │     ├─ typed.py        where typed text goes (private chats) and replies go (groups)
         │     ├─ groups.py       greeting when added to a group; anonymous admins / channel senders
         │     └─ router.py       ROUTES: first part of a button's route → screen handler
         ├─ modules/i18n/         interface text: en.py and fa.py (same keys), t(), level_label()
         ├─ modules/student.py    per-student settings (language, level) in darsai_student
         ├─ modules/input_mode.py which tool a student's typing goes to in a chat (darsai_input_mode)
         ├─ modules/ai.py         /chat /askai /ai /aihelp /newchat; AI memory, daily limit, provider client
         └─ modules/math/math.py  /math /mathhelp /level /lesson /math_tutor /solve /practice /quiz /check /progress /math_newchat
               ├─ plot.py         /plot (Pillow PNG)
               ├─ topics.py       TOPIC_MODULES, TOPIC_LEVEL, DEFAULT_TOPIC, TOPIC_ALIASES, MATH_MEMORY_TOPICS (no Telegram)
               ├─ shared.py       levels, difficulties, mastery, active questions, Expression parser, solver, answers_match, poly_text
               ├─ prompts.py      math tutor system prompt
               └─ <level>/<topic>.py   lesson() + practice() generators
modules/db.py      psycopg_pool connection pool (connection(), db_configured(), close_pool())
modules/common.py  LANGUAGES, extract_language(), split_message(), reply_long()
```

- **Webhook:** the webhook handler compares the `X-Telegram-Bot-Api-Secret-Token` header with `config.WEBHOOK_SECRET_TOKEN` and returns 403 if they don't match. The secret is `TELEGRAM_WEBHOOK_SECRET`, or a SHA-256 hash derived from the bot token if that is unset. The handler puts the update on `telegram_app.update_queue` and returns immediately, so a slow AI reply never holds the HTTP request open. `GET /` must not reveal the webhook path, and a test checks this.
- **Startup (`lifespan` in `main.py`):** creates the database tables with `init_databases()` (also used by `run_local.py`), starts the Application, sets the "/" menu (only /start and /help, in English and Persian), then calls `set_webhook` with the secret. Shutdown closes the database pool.
- **Button interface:** new buttons use callback data `d1:<owner user id>:<route>[:<arg>…]`, built with `Screen.button()` / `core.pack()` (Telegram's limit is 64 bytes). `router.callback_router` rejects presses by anyone but the owner with a pop-up, then dispatches on the first route part through `ROUTES`. Every main menu entry has a route; an unknown route shows "coming soon". Screens draw with `Screen.show()`, which edits the pressed message and falls back to sending a new one (e.g. when the message is a photo). Every `Screen` handler call ends with the button press answered.
- **Old buttons:** buttons in old messages (`menu:math`, `main:*`, `math_level:*`, `math_action:*`) open the new screens through `router.OLD_BUTTONS`, drawn for whoever presses them (they have no owner). Only `main:subscribe` (`main.py`) and `ai:newchat` (`ai.py`) keep their old handlers. `router.register_fallback_handlers` must be registered last: it answers any button nothing else knows, so Telegram never shows an endless spinner. `/math` and `/mathhelp` show the new menu.
- **Groups:** commands and replies sent as the group (anonymous admins) or as a channel share one user id, so a handler in group -1 asks them to post as themselves and stops the update. When the bot is added to a group (`my_chat_member`) it explains `/start` and replying. In forum groups, messages sent after a button press go to that topic (`Screen.thread_id`).
- **Languages:** the interface language is the student's choice in Settings, or a guess from their Telegram language code. Keyboards are mirrored for Persian (`core.arrange`). Private chats also get a persistent 🏠 Menu reply keyboard; its label in either language opens the menu.
- **Storage:** every storage function has two branches. When `db_configured()` is true it uses PostgreSQL. Otherwise it uses a module-level dict: `_MEMORY_FALLBACK` and `_USAGE_FALLBACK` in `ai.py`, `_FALLBACK` in `student.py` and `input_mode.py`, and `MASTERY_FALLBACK` and `ACTIVE_QUESTION_FALLBACK` in `shared.py`. Tests run against these dicts and clear them in `setUp`. The tables are `darsai_ai_messages`, `darsai_ai_usage`, `darsai_student`, `darsai_user_profile`, `darsai_mastery`, `darsai_active_question` and `darsai_input_mode`. Settings (language, level) are per student in `darsai_student` and follow them into every chat; `darsai_user_profile` is only read as a fallback for levels saved per chat before that. Mastery is per student too (`user_id, level, topic`). The old per-chat `darsai_math_progress` table (still in production) is never written; `init_math_db` copies its counts into `darsai_mastery` once, for students who have no mastery rows yet. The active practice question is keyed by `(chat_id, user_id)`, so students in the same group chat don't share it.
- **AI calls:** `ask_ai_with_memory()` takes one message from the daily limit (`reserve_ai_message`, an atomic SQL upsert), loads the history for `(chat_id, user_id, topic)`, calls the provider, gives the message back if the call fails, and saves the exchange. Memory topics are `general` for `/chat`, `math` for the tutor answer from `/solve`, and the canonical topic name (such as `quadratics`) for `/math_tutor`. `provider_config()` picks the URL and API key for groq, openrouter or openai. All three use the OpenAI chat-completions format through `httpx`.
- **Math flow:** `TOPIC_MODULES` in `topics.py` maps `(level, topic)` to a module that has `lesson()` and `practice(difficulty)`, and `DEFAULT_TOPIC` gives each level's fallback topic. Topic names are unique across levels (`TOPIC_LEVEL`), because callback data and AI memory use the topic alone. `/solve` uses `solve_equation()`, which fits a polynomial through x = 0, 1, 2, checks the fit at five more points, and raises `UnsupportedEquation` for anything that isn't linear or quadratic.
- **Practice flow (`ui/practice.py`):** the ✍️ Practice button and `/practice` both call `new_question()`, which saves the question (with an `id`, `attempts`, `mode` and the `message_ids` that show it) as the active question. Answers come from typed text in private chats (`home.text_message`), replies to those `message_ids` in groups (`group_reply`) and `/check`; all go to `handle_answer()`. Text that `readable_answer()` can't read doesn't use a try. A wrong answer gets one more try, then the solution. `finish()` removes the question with `clear_active_question(..., question_id)` first, so a result counts once, then calls `record_answer()`. Difficulty mode `a` uses `recommended_difficulty(mastery)`; `e`/`m`/`h` (🔽 Easier / 🔼 Harder) pin it. Typed text stops counting as an answer after 24 hours.
- **Typed text (`ui/typed.py`):** in private chats the 🏠 Menu label opens the menu and clears the input mode. Otherwise text goes to the open tool (tutor, solve, plot; `tools.current_mode`), else to the active practice question, else the student gets a nudge to the menu. Pressing a tool sets the input mode (`tools.start_mode`); the Menu button, `/start` and a new practice question clear it, and it ends after 24 hours. Opening a tool keeps the practice question, so after Menu typed text answers it again. In groups only replies count: to the tool's `message_ids` first, then to the practice question's. Change a stored input mode only with `change_input_mode` (one locked step, only while it has the same `id`, and only the fields given), never by writing back a state read before a slow tutor call.
- **Tools (`ui/tools.py`):** the tutor's memory topic is `math`, or the lesson's topic when opened from 📘 Learn. Solve shows `solve_equation()` results in the student's language: `SolveError.code` picks the message (`str(error)` stays English for the old `/solve`), and results get a 🧑‍🏫 Explain step by step button that asks the tutor once: `claim_last_result` lets only one of two quick taps through. Plot uses `parse_plot_input` and `create_plot` from `plot.py` and sends a photo. Solve and Plot show their `EXAMPLES` as copyable code and as one-tap buttons (`solve:e:<i>`, `plot:e:<i>`, which reopen the tool if needed), and answer input with several lines with "one per message".
- **Imports:** `modules/math/__init__.py` deliberately doesn't import `math.py`, so `shared.py` and the topic modules can be imported without python-telegram-bot.

## Conventions to keep

- Database functions are synchronous. Handlers must call them with `await asyncio.to_thread(fn, ...)`, never directly. Use `with connection() as conn, conn.cursor() as cur:`. The pool commits on success and rolls back on error.
- Tables are created once at startup (`init_ai_db` and `init_math_db` in `main.lifespan`), never per request.
- Every AI call goes through `ask_ai_with_memory()`, which charges the daily limit and refunds it if the call fails. Show users `ai_error_message(error)` (old commands) or `tools.ai_error_text(screen, error)` (buttons, translated), never the raw error. Both log through `log_ai_error`.
- Send AI output with `reply_long()` (old commands) or `Screen.send_long()` (buttons) so replies over 4000 characters are split. It is sent as plain text, so every tutor prompt includes `common.PLAIN_TEXT_RULE` (no Markdown, no LaTeX, Unicode math).
- Math input goes through `Expression` / `safe_eval` (an AST whitelist). Never use `eval`.
- Topic memory keys are canonical topic names (`linear_equations`, `quadratics`, …). Add aliases to `TOPIC_ALIASES` and new topic modules to `TOPIC_MODULES` in `topics.py`, plus a `topic.<name>` string in both languages. `MATH_MEMORY_TOPICS` is derived from `TOPIC_MODULES`.
- Practice generators take `"easy"`, `"medium"` or `"hard"` and return `{level, topic, difficulty, prompt, formula, answer, steps}`. `prompt` is a `prompt.<key>` string, `formula` a list of formula lines, and each step is `[key, params, formula]` for a `step.<key>` string. Step params are positive integers (a minus sign inside a Persian sentence gets reordered; use `number_step()`), and the last step's formula shows the answer. Format polynomials with `poly_text()`. `answers_match()` compares answers by value. The whole dict must survive a JSON round trip.
- `lesson()` returns `{level, topic, intro, example}`: `intro` is a list of `[full i18n key, params, formula or ""]`, and `example` is `{prompt, formula, steps}` in the practice format.
- Text students see in the button interface comes from `modules/i18n/en.py` and `fa.py`, never inline strings. Add every key to both files with the same `{placeholders}` (a test checks this). Persian uses casual «تو», and the user reviews all Persian text. Put formulas on their own line instead of inside a Persian sentence (`practice.formulas()` adds the left-to-right mark). Examples students may send back use `formulas(..., copy=True)`: they go out as Telegram code entities, so one tap copies just that line.
- Messages are plain text: never use `parse_mode`. Formatting is done with entities: `core.copyable()` marks text and `Screen.send`/`show`/`send_photo` turn the marks into code entities (offsets in UTF-16 units). Send through `Screen`, or the marks show up as odd characters.
- Everything students type goes through `strip_invisible()` (inside `normalize_expression`, `parse_plot_input` and `tools.handle_input`): a formula copied from a Persian message carries a left-to-right mark. A `/command` inside a Persian sentence needs `\u200e` right before it, or it shows as "start/" (a test checks this).
- Keep the httpx logger at WARNING (set in `main.py`). Its INFO logs include request URLs, and Telegram URLs contain the bot token.

## Local environment gotchas

- The default `python` is Anaconda base 3.8 with no dependencies, so tests fail with `No module named 'fastapi'`. python-telegram-bot 22.7 needs Python 3.10+. Suggested setup: `conda create -n darsai python=3.11 -y && conda activate darsai && pip install -r requirements.txt`.
- A 3.11 interpreter exists at `/Users/ali/opt/anaconda3/envs/rota/bin/python`. That env belongs to another project, so use it only to create a separate venv and never install into it.
- PostgreSQL binaries for a throwaway test database are in `/Users/ali/opt/anaconda3/envs/rota-pgtools/bin/` (`initdb`, `pg_ctl`). Listen on 127.0.0.1 with a custom port, use `--auth=trust`, and delete the data directory afterwards.
- The `gh` CLI is not installed, so PRs can't be opened from the terminal until the user runs `brew install gh` and `gh auth login`. Until then, push and let the user open the PR on github.com. `git push` uses the macOS Keychain login. Always ask the user before pushing.

## Deploying

After a merge to `main`, Render redeploys. On startup the bot creates any missing tables and registers the webhook again with the secret. To check it, open `https://api.telegram.org/bot<TOKEN>/getWebhookInfo`: `last_error_message` should be empty. Don't paste the token anywhere public. In production, set `DATABASE_URL`, because the in-memory fallbacks belong to a single process and are lost on restart.
