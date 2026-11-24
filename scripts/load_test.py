"""Load test: many simulated students use the bot at once, through the real handlers.

Each student goes through a typical session: /start and the three setup questions, the Math hub, two practice
questions answered by typing (one wrong first), Ask the tutor, Solve, Plot, Progress, Home, ▶️ Continue,
🔔 Notify me and a Premium pick. The updates go through telegram_app.process_update, as webhook updates do.
Telegram's API and the AI provider are replaced by stand-ins that wait a set time and answer, so nothing is
sent anywhere; everything else (handlers, storage, the database, Plot's drawing) is the real code.

    python scripts/load_test.py                                   # 300 students, in-memory storage
    python scripts/load_test.py --students 1000 --ramp 30
    python scripts/load_test.py --database-url postgresql://postgres@127.0.0.1:55432/darsai_load_test

With --database-url the database's name must contain "test": its darsai_* tables are dropped first.

The report: for each kind of update, how many, and how long the handler took (median, 95th percentile,
slowest), plus errors, throughput, the process's memory, and the updates the speed limit refused (each student
sends 20 updates; with a short --think some may come faster than RATE_LIMIT_ACTIONS per window).
"""

import argparse
import asyncio
import contextvars
import logging
import os
import random
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIRST_USER_ID = 9_000_000_000  # far from real Telegram user ids


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--students", type=int, default=300)
    parser.add_argument("--ramp", type=float, default=10.0, help="seconds over which the students arrive (0: all at once)")
    parser.add_argument("--think", type=float, default=0.5, help="average seconds a student waits between actions")
    parser.add_argument("--telegram-ms", type=float, default=60.0, help="how long each Telegram API call takes")
    parser.add_argument("--ai-seconds", type=float, default=1.5, help="how long the AI provider takes to answer")
    parser.add_argument("--database-url", default="", help="a PostgreSQL test database (its name must contain 'test')")
    parser.add_argument("--pool", type=int, default=0, help="DB_POOL_MAX_SIZE for the run (default: the setting, 5)")
    parser.add_argument("--seed", type=int, default=1)
    return parser.parse_args(argv)


def prepare_environment(args) -> None:
    """Settings for the run, before config.py is imported."""
    os.environ.update(
        TELEGRAM_BOT_TOKEN="123456:LOAD_TEST_TOKEN",
        WEBHOOK_URL="https://example.com",
        DATABASE_URL=args.database_url,
        FREE_DAILY_AI_LIMIT="1000",
        ADMIN_USER_IDS="",
        ALERTS_TO_ADMINS="false",
        SENTRY_DSN="",
    )
    if args.pool:
        os.environ["DB_POOL_MAX_SIZE"] = str(args.pool)
    if args.database_url:
        name = urlparse(args.database_url).path.lstrip("/")
        if "test" not in name.lower():
            sys.exit(f"Refusing: the database name must contain 'test' (got {name!r}); its darsai_* tables are dropped.")


# The database connections the current update borrowed (a list, so the copies in worker threads add to it).
_borrowed: contextvars.ContextVar = contextvars.ContextVar("borrowed")


class Recorder:
    def __init__(self):
        self.times = {}
        self.connections = {}
        self.errors = 0
        self.busy = 0  # questions that found no free AI call slot (ai.note_busy)

    def add(self, kind: str, seconds: float) -> None:
        self.times.setdefault(kind, []).append(seconds)


class CountErrors(logging.Handler):
    """Errors, and "the tutor is busy" (a WARNING from modules.ai, see ai.note_busy)."""

    def __init__(self, recorder: Recorder):
        super().__init__(level=logging.WARNING)
        self.recorder = recorder

    def emit(self, record):
        if record.levelno >= logging.ERROR:
            self.recorder.errors += 1
        elif record.name == "modules.ai" and str(record.msg).startswith("AI capacity"):
            self.recorder.busy += 1


def percentile(values, share):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(share * (len(ordered) - 1))))]


async def main_async(args) -> None:
    import_started = time.monotonic()
    import main
    from telegram import CallbackQuery, Message, Update
    from telegram.ext import ExtBot

    import config
    from modules import ai, db, metrics, ratelimit
    from modules.db import connection
    from modules.math import shared
    imported = time.monotonic() - import_started
    _, peak_after_import = metrics.memory_mb()

    app, bot = main.telegram_app, main.telegram_app.bot
    if db.db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = current_schema() AND tablename LIKE 'darsai%%'")
            for (table,) in cur.fetchall():
                cur.execute(f'DROP TABLE "{table}" CASCADE')
    started = time.monotonic()
    await asyncio.to_thread(main.init_databases)
    migrated = time.monotonic() - started
    if db.db_configured():
        pool = db._get_pool()
        borrow = pool.connection

        def counting_connection(*args, **kwargs):
            counter = _borrowed.get(None)
            if counter is not None:
                counter.append(1)
            return borrow(*args, **kwargs)

        pool.connection = counting_connection

    message_ids = iter(range(1000, 10 ** 9))

    async def telegram_call(*args, **kwargs):
        await asyncio.sleep(args_.telegram_ms / 1000)
        return SimpleNamespace(message_id=next(message_ids))

    async def ai_answer(*args, **kwargs):
        await asyncio.sleep(args_.ai_seconds)
        return "Step 1: think about it. Step 2: you've got it."

    args_ = args
    patches = [
        patch.object(app, "_initialized", True),
        patch.object(type(bot), "username", PropertyMock(return_value="darsai_load_test_bot")),
        patch.object(ai, "call_ai_provider", AsyncMock(side_effect=ai_answer)),
    ]
    for owner, name in ((Message, "reply_text"), (Message, "reply_photo"), (CallbackQuery, "answer"),
                        (CallbackQuery, "edit_message_text"), (CallbackQuery, "edit_message_reply_markup"),
                        (ExtBot, "send_message"), (ExtBot, "send_photo"), (ExtBot, "edit_message_reply_markup"),
                        (ExtBot, "send_chat_action")):
        patches.append(patch.object(owner, name, AsyncMock(side_effect=telegram_call)))
    for p in patches:
        p.start()

    recorder = Recorder()
    root = logging.getLogger()
    error_counter, old_level = CountErrors(recorder), root.level
    root.addHandler(error_counter)
    root.setLevel(logging.WARNING)  # no INFO lines for thousands of updates
    # PTB runs at most this many updates at once with concurrent_updates=True.
    slots = asyncio.Semaphore(256)
    rng = random.Random(args.seed)
    update_ids = iter(range(1, 10 ** 9))
    date = 1_700_000_000

    def user(user_id, lang):
        return {"id": user_id, "is_bot": False, "first_name": "Student", "language_code": lang}

    def text_update(user_id, lang, text):
        message = {"message_id": next(message_ids), "date": date, "chat": {"id": user_id, "type": "private"},
                   "from": user(user_id, lang), "text": text}
        if text.startswith("/"):
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        return Update.de_json({"update_id": next(update_ids), "message": message}, bot)

    def button_update(user_id, lang, route):
        message = {"message_id": next(message_ids), "date": date, "chat": {"id": user_id, "type": "private"},
                   "from": {"id": 1, "is_bot": True, "first_name": "DarsAI"}, "text": "previous screen"}
        query = {"id": str(next(update_ids)), "from": user(user_id, lang), "chat_instance": "c",
                 "data": f"d1:{user_id}:{route}", "message": message}
        return Update.de_json({"update_id": next(update_ids), "callback_query": query}, bot)

    async def send(kind, update):
        async with slots:
            counter = []
            _borrowed.set(counter)
            began = time.monotonic()
            await app.process_update(update)
            recorder.add(kind, time.monotonic() - began)
            recorder.connections.setdefault(kind, []).append(len(counter))
        await asyncio.sleep(rng.expovariate(1 / args.think) if args.think > 0 else 0)

    async def answer(user_id):
        question = await asyncio.to_thread(shared.get_active_question, user_id, user_id)
        return question["answer"] if question else "1"

    async def session(number):
        await asyncio.sleep(rng.uniform(0, args.ramp) if args.ramp > 0 else 0)
        uid, lang = FIRST_USER_ID + number, ("fa" if number % 2 else "en")
        await send("/start (setup question 1)", text_update(uid, lang, "/start"))
        await send("setup: language", button_update(uid, lang, f"su:l:{lang}"))
        await send("setup: level", button_update(uid, lang, "su:v:high_school"))
        await send("setup: first course (Math hub)", button_update(uid, lang, "su:c:math"))
        await send("practice: new question", button_update(uid, lang, "c:math:prac:n:algebra"))
        await send("practice: typed answer", text_update(uid, lang, await answer(uid)))
        await send("practice: new question", button_update(uid, lang, "c:math:prac:n:quadratics"))
        await send("practice: typed answer", text_update(uid, lang, "1000, 2000"))
        await send("practice: typed answer", text_update(uid, lang, await answer(uid)))
        await send("tutor: open", button_update(uid, lang, "c:math:tutor"))
        await send("tutor: question (AI)", text_update(uid, lang, "Why does the quadratic formula work?"))
        await send("solve: open", button_update(uid, lang, "c:math:solve"))
        await send("solve: equation", text_update(uid, lang, "x^2 - 5x + 6 = 0"))
        await send("plot: open", button_update(uid, lang, "c:math:plot"))
        await send("plot: graph (drawing)", text_update(uid, lang, "y = x^2 - 4x + 3"))
        await send("progress", button_update(uid, lang, "prog"))
        await send("home", button_update(uid, lang, "home"))
        await send("continue", button_update(uid, lang, "cont"))
        await send("notify me", button_update(uid, lang, "c:physics:n"))
        await send("premium pick", button_update(uid, lang, "prem:a:photo:m"))

    ratelimit.clear()
    began = time.monotonic()
    try:
        await asyncio.gather(*(session(n) for n in range(args.students)))
    finally:
        for p in patches:
            p.stop()
        root.removeHandler(error_counter)
        root.setLevel(old_level)
    total = time.monotonic() - began
    current, peak = metrics.memory_mb()
    if db.db_configured():
        await asyncio.to_thread(db.close_pool)

    updates = sum(len(v) for v in recorder.times.values())
    storage = "PostgreSQL" if args.database_url else "in-memory"
    print(f"\n{args.students} students, {updates} updates in {total:.1f} s ({updates / total:.0f} updates/s), storage: {storage}")
    print(f"Arrivals over {args.ramp:.0f} s, ~{args.think:.1f} s between a student's actions, Telegram calls "
          f"{args.telegram_ms:.0f} ms, AI answers {args.ai_seconds:.1f} s, DB pool {os.environ.get('DB_POOL_MAX_SIZE', '5')}")
    print(f"Import {imported:.1f} s, database setup {migrated:.2f} s, errors logged: {recorder.errors}, "
          f"tutor busy: {recorder.busy} (AI call slots: {config.AI_MAX_CONCURRENT_CALLS})")
    print(f"Speed limit: {ratelimit.ACTIONS.refused} updates refused ({config.RATE_LIMIT_ACTIONS} per "
          f"{config.RATE_LIMIT_WINDOW_SECONDS} s)")
    print(f"Memory: peak {peak_after_import:.0f} MB after import, peak {peak:.0f} MB after the run"
          + (f", {current:.0f} MB now" if current is not None else ""))
    print(f"\n{'update':34} {'count':>6} {'median':>9} {'95%':>9} {'slowest':>9} {'DB calls':>9}")
    for kind, values in recorder.times.items():
        calls = recorder.connections.get(kind, [0])
        print(f"{kind:34} {len(values):6} {statistics.median(values) * 1000:7.0f}ms "
              f"{percentile(values, 0.95) * 1000:7.0f}ms {max(values) * 1000:7.0f}ms {statistics.median(calls):9.0f}")
    return recorder


def main_entry(argv=None):
    args = parse_args(argv)
    prepare_environment(args)
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main_entry()
