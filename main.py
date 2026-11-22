import asyncio
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from telegram import BotCommand, Update
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from config import BOT_NAME, SECRET_PATH, TOKEN, WEBHOOK_SECRET_TOKEN, WEBHOOK_URL
from modules.activity import init_activity_db, init_first_seen_db
from modules.ai import ai_callback_handler, init_ai_db, register_ai_handlers
from modules.db import close_pool
from modules.input_mode import init_input_db
from modules.math.math import register_math_handlers
from modules.math.shared import init_math_db
from modules.i18n import detect_language, t
from modules.notify import init_notify_db
from modules.premium import init_premium_db
from modules.stats import register_stats_handlers
from modules.student import init_setup_db, init_student_db
from modules.ui.core import Screen
from modules.ui.home import home_view
from modules.ui.router import register_fallback_handlers, register_ui_handlers

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
# httpx logs every request URL at INFO, and Telegram URLs contain the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("darsai")

if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")
if not WEBHOOK_URL:
    raise RuntimeError("Missing WEBHOOK_URL environment variable.")

WEBHOOK_PATH = SECRET_PATH.strip("/") if SECRET_PATH else "darsai-webhook"
FULL_WEBHOOK_URL = f"{WEBHOOK_URL.rstrip('/')}/{WEBHOOK_PATH}"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

# Handle updates concurrently so one slow AI answer does not hold up every other student.
telegram_app = Application.builder().token(TOKEN).concurrent_updates(True).build()


def help_text() -> str:
    return (
        f"{BOT_NAME} help 📚\n\n"
        "Tip: you don't need commands. Tap /start and use the buttons.\n\n"
        "Main commands:\n"
        "/start - open the main menu\n"
        "/math - open the math menu\n"
        "/mathhelp - math command guide\n"
        "/level high_school - set your level\n"
        "/lesson high_school quadratics - get a lesson\n"
        "/math_tutor high_school algebra explain equations\n"
        "/solve 2x + 5 = 17\n"
        "/practice high_school algebra\n"
        "/quiz university calculus\n"
        "/check answer - check last practice answer\n"
        "/plot y=x^2 range -5 5\n"
        "/progress - show progress\n"
        "/aihelp - AI tools\n"
        "/newchat - clear general AI chat memory\n\n"
        "Tutor languages:\n"
        "/math_tutor fa high_school quadratics explain quadratic formula"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.effective_chat:
        return
    _, markup = await home_view(await Screen.load(update, context))
    await update.message.reply_text(help_text(), reply_markup=markup)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Error while handling an update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        # The language from Telegram only: the database may be what failed.
        lang = detect_language(update.effective_user.language_code if update.effective_user else None)
        try:
            await update.effective_message.reply_text(t(lang, "error.generic"))
        except Exception:
            logger.warning("Could not send the error message to the user.")


async def setup_bot_commands() -> None:
    """Telegram's "/" menu shows only /start and /help. Every other command still works when typed."""
    for language_code in (None, "fa"):
        lang = language_code or "en"
        commands = [BotCommand("start", t(lang, "command.start")), BotCommand("help", t(lang, "command.help"))]
        await telegram_app.bot.set_my_commands(commands, language_code=language_code)


async def setup_bot_descriptions() -> None:
    """The description (an empty chat, before Start) and short description (profile, shared links).

    Only changed when the text differs, and a failure is only logged: it must not stop the bot.
    """
    bot = telegram_app.bot
    for language_code in (None, "fa"):  # None: everyone whose Telegram isn't in Persian
        lang = language_code or "en"
        description = t(lang, "bot.description", bot=BOT_NAME)
        short_description = t(lang, "bot.short_description", bot=BOT_NAME)
        try:
            if (await bot.get_my_description(language_code=language_code)).description != description:
                await bot.set_my_description(description, language_code=language_code)
            current = await bot.get_my_short_description(language_code=language_code)
            if current.short_description != short_description:
                await bot.set_my_short_description(short_description, language_code=language_code)
        except TelegramError as error:
            logger.warning("Could not set the bot's %s description: %s", lang, error)


def register_handlers() -> None:
    register_stats_handlers(telegram_app)  # includes the activity tracker, which runs before everything else
    register_ui_handlers(telegram_app)
    telegram_app.add_handler(CommandHandler("help", help_command))
    register_ai_handlers(telegram_app)
    register_math_handlers(telegram_app)
    telegram_app.add_handler(CallbackQueryHandler(ai_callback_handler, pattern=r"^ai:"))
    register_fallback_handlers(telegram_app)  # last: answers buttons nothing above knows
    telegram_app.add_error_handler(error_handler)


register_handlers()


def init_databases() -> None:
    """Blocking. Create every table once at startup."""
    init_ai_db()
    init_math_db()
    init_student_db()
    init_input_db()
    init_activity_db()
    init_premium_db()
    init_notify_db()
    init_first_seen_db()  # after the others: the first time, it copies in the students the other tables know
    init_setup_db()  # last: the first time, it marks every student in darsai_first_seen as set up


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(init_databases)
    await telegram_app.initialize()
    await telegram_app.start()
    await setup_bot_commands()
    await setup_bot_descriptions()
    await telegram_app.bot.set_webhook(
        url=FULL_WEBHOOK_URL,
        allowed_updates=Update.ALL_TYPES,
        secret_token=WEBHOOK_SECRET_TOKEN,
    )
    logger.info("%s webhook registered.", BOT_NAME)
    try:
        yield
    finally:
        await telegram_app.stop()
        await telegram_app.shutdown()
        await asyncio.to_thread(close_pool)


api = FastAPI(title=f"{BOT_NAME} Telegram Tutor Bot", lifespan=lifespan)


@api.get("/")
async def root():
    return {
        "status": "ok",
        "bot": BOT_NAME,
        "product": "AI tutor MVP",
        "mvp_modules": ["ai", "math", "plot"],
        "future_modules": ["physics", "chemistry", "biology", "data_science"],
    }


@api.get("/health")
async def health():
    return {"status": "healthy", "bot": BOT_NAME}


@api.post(f"/{WEBHOOK_PATH}")
async def telegram_webhook(request: Request):
    received_secret = request.headers.get(SECRET_HEADER, "")
    if not hmac.compare_digest(received_secret.encode(), WEBHOOK_SECRET_TOKEN.encode()):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        data = await request.json()
        update = Update.de_json(data, telegram_app.bot)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid update")
    if update is not None:
        # Queue it and answer Telegram right away; slow AI replies must not hold the request open.
        await telegram_app.update_queue.put(update)
    return {"ok": True}
