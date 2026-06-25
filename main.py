from fastapi import FastAPI, Request, HTTPException
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from config import BOT_NAME, SECRET_PATH, TOKEN, WEBHOOK_URL
from modules.ai import ai_callback_handler, aihelp_command, init_ai_db, register_ai_handlers
from modules.math.math import register_math_handlers
from modules.math.shared import init_math_db

if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")
if not WEBHOOK_URL:
    raise RuntimeError("Missing WEBHOOK_URL environment variable.")

WEBHOOK_PATH = SECRET_PATH.strip("/") if SECRET_PATH else "darsai-webhook"
FULL_WEBHOOK_URL = f"{WEBHOOK_URL.rstrip('/')}/{WEBHOOK_PATH}"

telegram_app = Application.builder().token(TOKEN).build()
api = FastAPI(title=f"{BOT_NAME} Telegram Tutor Bot")


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎓 Choose level", callback_data="main:level"), InlineKeyboardButton("🧮 Math tutor", callback_data="menu:math")],
        [InlineKeyboardButton("✍️ Practice", callback_data="main:practice"), InlineKeyboardButton("📈 Plot", callback_data="main:plot")],
        [InlineKeyboardButton("🤖 AI help", callback_data="main:ai"), InlineKeyboardButton("📊 Progress", callback_data="main:progress")],
        [InlineKeyboardButton("💎 Subscription", callback_data="main:subscribe")],
    ])


def start_text() -> str:
    return (
        f"Welcome to {BOT_NAME} 🎓\n\n"
        "Not just answers. Real learning.\n\n"
        "I help students learn step by step with lessons, practice, quizzes, plotting, and AI tutor explanations.\n\n"
        "Start here:\n"
        "1. Choose your level\n"
        "2. Pick a math topic\n"
        "3. Learn, practice, check answers, and track progress\n\n"
        "Current MVP: Math tutor.\n"
        "Coming later: Physics, Chemistry, Biology, Data Science, and more."
    )


def help_text() -> str:
    return (
        f"{BOT_NAME} help 📚\n\n"
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


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(start_text(), reply_markup=start_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(help_text(), reply_markup=start_keyboard())


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "Subscription MVP 💎\n\n"
        "For now, DarsAI is in MVP/free testing mode.\n\n"
        "Future plans:\n"
        "Free: basic tutor and daily AI limit\n"
        "Premium: more AI tutor messages, progress insights, personalized study plans\n\n"
        "Payment integration will be added after the learning MVP is validated."
    )


async def main_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""
    if data == "menu:math":
        await query.edit_message_text(
            "Math menu 🧮\n\n"
            "Use /math to open the full math menu.\n\n"
            "Quick examples:\n"
            "/lesson high_school algebra\n"
            "/practice high_school quadratics\n"
            "/math_tutor fa high_school quadratics explain quadratic formula",
        )
    elif data == "main:level":
        await query.edit_message_text(
            "Choose your level with one command:\n\n"
            "/level middle_school\n"
            "/level high_school\n"
            "/level pre_college\n"
            "/level university"
        )
    elif data == "main:practice":
        await query.edit_message_text(
            "Practice examples ✍️\n\n"
            "/practice middle_school linear_equations\n"
            "/practice high_school algebra\n"
            "/practice high_school quadratics\n"
            "/practice university calculus"
        )
    elif data == "main:plot":
        await query.edit_message_text(
            "Plot examples 📈\n\n"
            "/plot y=x^2 range -5 5\n"
            "/plot sin(x) range -6.28 6.28\n"
            "/plot y=x^2-4x+3 range -5 8"
        )
    elif data == "main:ai":
        await query.edit_message_text(
            "AI tools 🤖\n\n"
            "/aihelp - AI help\n"
            "/chat explain how to study algebra\n"
            "/math_tutor high_school algebra explain linear equations"
        )
    elif data == "main:progress":
        await query.edit_message_text("Use /progress to see your math progress.")
    elif data == "main:subscribe":
        await query.edit_message_text(
            "Subscription MVP 💎\n\n"
            "DarsAI is currently in free MVP testing mode. Premium plans will be added later."
        )


async def setup_bot_commands() -> None:
    commands = [
        BotCommand("start", "Open DarsAI menu"),
        BotCommand("help", "Help"),
        BotCommand("math", "Math menu"),
        BotCommand("mathhelp", "Math help"),
        BotCommand("math_tutor", "AI math tutor"),
        BotCommand("solve", "Solve math"),
        BotCommand("practice", "Practice math"),
        BotCommand("quiz", "Quiz"),
        BotCommand("check", "Check answer"),
        BotCommand("plot", "Plot function"),
        BotCommand("progress", "Progress"),
        BotCommand("aihelp", "AI help"),
        BotCommand("chat", "AI chat"),
        BotCommand("subscribe", "Subscription"),
    ]
    await telegram_app.bot.set_my_commands(commands[:100])


def register_handlers() -> None:
    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CommandHandler("help", help_command))
    telegram_app.add_handler(CommandHandler("subscribe", subscribe_command))
    register_ai_handlers(telegram_app)
    register_math_handlers(telegram_app)
    telegram_app.add_handler(CallbackQueryHandler(main_callback_handler, pattern=r"^(main:|menu:)"))
    telegram_app.add_handler(CallbackQueryHandler(ai_callback_handler, pattern=r"^ai:"))


register_handlers()


@api.on_event("startup")
async def on_startup() -> None:
    init_ai_db()
    init_math_db()
    await telegram_app.initialize()
    await telegram_app.start()
    await setup_bot_commands()
    await telegram_app.bot.set_webhook(url=FULL_WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
    print(f"{BOT_NAME} webhook set to: {FULL_WEBHOOK_URL}")


@api.on_event("shutdown")
async def on_shutdown() -> None:
    await telegram_app.stop()
    await telegram_app.shutdown()


@api.get("/")
async def root():
    return {
        "status": "ok",
        "bot": BOT_NAME,
        "product": "AI tutor MVP",
        "webhook": FULL_WEBHOOK_URL,
        "mvp_modules": ["ai", "math", "plot"],
        "future_modules": ["physics", "chemistry", "biology", "data_science"],
    }


@api.get("/health")
async def health():
    return {"status": "healthy", "bot": BOT_NAME}


@api.post(f"/{WEBHOOK_PATH}")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    try:
        update = Update.de_json(data, telegram_app.bot)
        await telegram_app.process_update(update)
    except Exception as error:
        print(f"Webhook processing error: {error}")
        return {"ok": False, "error": str(error)}
    return {"ok": True}
