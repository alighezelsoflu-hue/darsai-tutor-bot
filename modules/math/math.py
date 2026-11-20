import asyncio
from typing import Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from config import BOT_NAME
from modules.ai import ai_error_message, ask_ai_with_memory, clear_history
from modules.common import LANGUAGES, extract_language, reply_long
from .plot import register_plot_handlers
from .prompts import math_tutor_prompt
from .shared import (
    LEVEL_LABELS,
    UnsupportedEquation,
    answers_match,
    clear_active_question,
    get_active_question,
    get_user_level,
    nice,
    normalize_level,
    normalize_topic,
    progress_report,
    record_progress,
    save_active_question,
    set_user_level,
    solve_equation,
)
from .middle_school import equations as middle_equations
from .high_school import algebra as high_algebra
from .high_school import quadratics as high_quadratics
from .pre_college import precalculus as pre_calculus
from .university import calculus as uni_calculus


TOPIC_MODULES = {
    ("middle_school", "linear_equations"): middle_equations,
    ("high_school", "algebra"): high_algebra,
    ("high_school", "quadratics"): high_quadratics,
    ("pre_college", "precalculus"): pre_calculus,
    ("university", "calculus"): uni_calculus,
}

TOPIC_ALIASES = {
    "equations": "linear_equations",
}

DEFAULT_TOPIC = {
    "middle_school": "linear_equations",
    "high_school": "algebra",
    "pre_college": "precalculus",
    "university": "calculus",
}

# Every AI memory topic the math tutor writes to ("math" is used by /solve tutor).
MATH_MEMORY_TOPICS = ("math",) + tuple(sorted({topic for _, topic in TOPIC_MODULES}))


def math_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Middle School", callback_data="math_level:middle_school"), InlineKeyboardButton("High School", callback_data="math_level:high_school")],
        [InlineKeyboardButton("Pre-College", callback_data="math_level:pre_college"), InlineKeyboardButton("University", callback_data="math_level:university")],
        [InlineKeyboardButton("🧠 Math tutor", callback_data="math_action:tutor"), InlineKeyboardButton("✍️ Practice", callback_data="math_action:practice")],
        [InlineKeyboardButton("📈 Plot", callback_data="math_action:plot"), InlineKeyboardButton("📊 Progress", callback_data="math_action:progress")],
    ])


def math_help_text() -> str:
    return (
        f"{BOT_NAME} Math Tutor 🧮\n\n"
        "Choose a level and learn step by step.\n\n"
        "Levels:\n"
        "- middle_school: equations, fractions later\n"
        "- high_school: algebra, quadratics\n"
        "- pre_college: precalculus\n"
        "- university: calculus\n\n"
        "Commands:\n"
        "/level high_school - set your math level\n"
        "/lesson high_school quadratics - get a lesson\n"
        "/math_tutor high_school algebra explain linear equations\n"
        "/solve 2x + 5 = 17\n"
        "/practice high_school quadratics\n"
        "/quiz university calculus\n"
        "/check your answer - check last practice answer\n"
        "/plot y=x^2-4x+3 range -5 8\n"
        "/progress - show your progress\n"
        "/math_newchat - clear your math tutor memory\n\n"
        "Languages for tutor mode:\n"
        "/math_tutor fa high_school quadratics explain the quadratic formula\n"
    )


def parse_level_topic_text(text: str, fallback_level: str) -> Tuple[str, str, str]:
    """Split "[level] [topic] rest..." into (level, canonical topic, rest)."""
    parts = text.strip().split()
    level = fallback_level
    topic = DEFAULT_TOPIC.get(level, "algebra")
    consumed = 0
    if parts:
        maybe_level = normalize_level(parts[0], default="")
        if maybe_level:
            level = maybe_level
            topic = DEFAULT_TOPIC.get(level, topic)
            consumed = 1
    if len(parts) > consumed:
        maybe_topic = normalize_topic(parts[consumed])
        maybe_topic = TOPIC_ALIASES.get(maybe_topic, maybe_topic)
        if (level, maybe_topic) in TOPIC_MODULES:
            topic = maybe_topic
            consumed += 1
    rest = " ".join(parts[consumed:]).strip()
    return level, topic, rest


def get_topic_module(level: str, topic: str):
    topic = normalize_topic(topic)
    topic = TOPIC_ALIASES.get(topic, topic)
    return TOPIC_MODULES.get((level, topic)) or TOPIC_MODULES.get((level, DEFAULT_TOPIC.get(level, "algebra")))


async def math_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.effective_chat:
        return
    level = await asyncio.to_thread(get_user_level, update.effective_chat.id, update.effective_user.id)
    await update.message.reply_text(
        f"Welcome to {BOT_NAME} Math 🧮\n\nYour current level: {LEVEL_LABELS.get(level, level)}\n\nWhat would you like to do?",
        reply_markup=math_main_keyboard(),
    )


async def mathhelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(math_help_text(), reply_markup=math_main_keyboard())


LEVEL_USAGE = "Usage: /level middle_school | high_school | pre_college | university"


async def level_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.effective_chat:
        return
    chat_id, user_id = update.effective_chat.id, update.effective_user.id
    if not context.args:
        current = await asyncio.to_thread(get_user_level, chat_id, user_id)
        await update.message.reply_text(f"Current level: {LEVEL_LABELS.get(current, current)}\n\n{LEVEL_USAGE}")
        return
    requested = normalize_level(context.args[0], default="")
    if not requested:
        await update.message.reply_text(f"I don't know the level \"{context.args[0]}\".\n\n{LEVEL_USAGE}")
        return
    level = await asyncio.to_thread(set_user_level, chat_id, user_id, requested)
    await update.message.reply_text(f"Your math level is now: {LEVEL_LABELS.get(level, level)}")


async def lesson_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    fallback = await asyncio.to_thread(get_user_level, update.effective_chat.id, update.effective_user.id)
    level, topic, _ = parse_level_topic_text(" ".join(context.args or []), fallback)
    module = get_topic_module(level, topic)
    if not module:
        await update.message.reply_text("I do not have that topic yet. Try /mathhelp")
        return
    await update.message.reply_text(module.lesson(topic))


async def math_tutor_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    raw = " ".join(context.args or []).strip()
    if not raw and update.message.reply_to_message:
        raw = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
    raw, language = extract_language(raw)
    fallback = await asyncio.to_thread(get_user_level, update.effective_chat.id, update.effective_user.id)
    level, topic, question = parse_level_topic_text(raw, fallback)
    if not question:
        await update.message.reply_text(
            "Usage:\n"
            "/math_tutor high_school algebra explain linear equations\n"
            "/math_tutor fa high_school quadratics explain quadratic formula"
        )
        return
    await update.message.reply_text("DarsAI tutor is thinking...")
    prompt = math_tutor_prompt(level, topic, language)
    try:
        answer = await ask_ai_with_memory(
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            topic=topic,
            user_prompt=question,
            system_prompt=prompt,
            max_tokens=1000,
            temperature=0.22,
        )
    except Exception as error:
        await update.message.reply_text(ai_error_message(error))
        return
    await reply_long(update.message, answer)


async def solve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    tokens = list(context.args or [])
    wants_tutor = False
    language = "English"
    lowered = [t.lower() for t in tokens]
    if "tutor" in lowered:
        idx = lowered.index("tutor")
        wants_tutor = True
        if idx + 1 < len(tokens) and lowered[idx + 1] in LANGUAGES:
            language = LANGUAGES[lowered[idx + 1]]
            tokens.pop(idx + 1)
        tokens.pop(idx)
    raw = " ".join(tokens).strip()
    if not raw:
        await update.message.reply_text("Usage:\n/solve 2x + 5 = 17\n/solve x^2 - 5x + 6 = 0 tutor fa")
        return
    try:
        result = solve_equation(raw)
    except UnsupportedEquation as error:
        await update.message.reply_text(str(error))
        return
    except ValueError as error:
        await update.message.reply_text(f"Solve error: {error}")
        return
    if result["type"] == "arithmetic":
        report = f"Result: {nice(result['result'])}"
    elif result["type"] == "linear":
        report = f"Linear equation solution:\nx = {nice(result['solutions'][0])}"
    else:
        sols = result["solutions"]
        sol_text = ", ".join(nice(v) for v in sols) if sols else "No real solutions"
        report = f"Quadratic equation solution:\nDiscriminant = {nice(result['discriminant'])}\nSolutions: {sol_text}"
    await update.message.reply_text(report)
    if wants_tutor:
        level = await asyncio.to_thread(get_user_level, update.effective_chat.id, update.effective_user.id)
        try:
            explanation = await ask_ai_with_memory(
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                topic="math",
                user_prompt=f"Explain this math solution step by step. Problem: {raw}\nResult:\n{report}",
                system_prompt=math_tutor_prompt(level, "solve", language),
                max_tokens=900,
                temperature=0.22,
            )
        except Exception as error:
            await update.message.reply_text(ai_error_message(error))
            return
        await reply_long(update.message, explanation)


async def practice_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    chat_id, user_id = update.effective_chat.id, update.effective_user.id
    fallback = await asyncio.to_thread(get_user_level, chat_id, user_id)
    level, topic, rest = parse_level_topic_text(" ".join(context.args or []), fallback)
    module = get_topic_module(level, topic)
    if not module:
        await update.message.reply_text("Topic not found. Try /mathhelp")
        return
    question = module.practice(rest or "medium")
    await asyncio.to_thread(save_active_question, chat_id, user_id, question)
    await update.message.reply_text(
        f"Practice — {LEVEL_LABELS.get(question['level'], question['level'])} / {question['topic']} ✍️\n\n"
        f"{question['question']}\n\n"
        "Reply with /check your_answer"
    )


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await practice_command(update, context)


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    chat_id, user_id = update.effective_chat.id, update.effective_user.id
    question = await asyncio.to_thread(get_active_question, chat_id, user_id)
    if not question:
        await update.message.reply_text("No active practice question. Try /practice high_school algebra")
        return
    answer = " ".join(context.args or []).strip()
    if not answer:
        await update.message.reply_text("Usage: /check your_answer")
        return
    correct = answers_match(str(question["answer"]), answer)
    await asyncio.to_thread(record_progress, chat_id, user_id, question["level"], question["topic"], correct)
    if correct:
        await asyncio.to_thread(clear_active_question, chat_id, user_id)
        await update.message.reply_text(f"Correct ✅\n\n{question['explanation']}")
    else:
        await update.message.reply_text(
            "Not quite yet. That is okay — mistakes are part of learning.\n\n"
            f"Expected answer: {question['answer']}\n"
            f"Explanation: {question['explanation']}\n\n"
            "Try another one with /practice"
        )


async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    report = await asyncio.to_thread(progress_report, update.effective_chat.id, update.effective_user.id)
    await update.message.reply_text(report)


async def math_newchat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    deleted = await asyncio.to_thread(
        clear_history, update.effective_chat.id, update.effective_user.id, MATH_MEMORY_TOPICS
    )
    await update.message.reply_text(f"Cleared {deleted} math tutor memory messages." if deleted else "No math tutor memory to clear.")


async def math_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user or not update.effective_chat:
        return
    await query.answer()
    data = query.data or ""
    chat_id, user_id = update.effective_chat.id, update.effective_user.id
    if data.startswith("math_level:"):
        level = await asyncio.to_thread(set_user_level, chat_id, user_id, data.split(":", 1)[1])
        await query.edit_message_text(f"Math level set to {LEVEL_LABELS.get(level, level)}.\n\nUse /practice or /math_tutor to start.")
    elif data == "math_action:tutor":
        await query.edit_message_text("Use:\n/math_tutor high_school algebra explain linear equations\n\nOr in Farsi:\n/math_tutor fa high_school quadratics explain quadratic formula")
    elif data == "math_action:practice":
        await query.edit_message_text("Use:\n/practice high_school algebra\n/practice high_school quadratics\n/practice university calculus")
    elif data == "math_action:plot":
        await query.edit_message_text("Use:\n/plot y=x^2 range -5 5\n/plot sin(x) range -6.28 6.28")
    elif data == "math_action:progress":
        report = await asyncio.to_thread(progress_report, chat_id, user_id)
        await query.edit_message_text(report)


def register_math_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("math", math_command))
    app.add_handler(CommandHandler("mathhelp", mathhelp_command))
    app.add_handler(CommandHandler("level", level_command))
    app.add_handler(CommandHandler("lesson", lesson_command))
    app.add_handler(CommandHandler("math_tutor", math_tutor_command))
    app.add_handler(CommandHandler("mathtutor", math_tutor_command))
    app.add_handler(CommandHandler("solve", solve_command))
    app.add_handler(CommandHandler("practice", practice_command))
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CommandHandler("progress", progress_command))
    app.add_handler(CommandHandler("math_newchat", math_newchat_command))
    register_plot_handlers(app)
    app.add_handler(CallbackQueryHandler(math_callback_handler, pattern=r"^math_"))
