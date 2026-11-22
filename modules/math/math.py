import asyncio
from typing import Tuple

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import BOT_NAME
from modules.ai import ai_error_message, ask_ai_with_memory, clear_history
from modules.common import LANGUAGES, extract_language, reply_long
from modules.ui import home, learn, practice
from modules.ui.core import Screen
from .plot import register_plot_handlers
from .prompts import math_tutor_prompt
from .shared import (
    LEVEL_LABELS,
    UnsupportedEquation,
    get_user_level,
    nice,
    normalize_difficulty,
    normalize_level,
    progress_report,
    set_user_level,
    solve_equation,
)
from .topics import DEFAULT_TOPIC, MATH_MEMORY_TOPICS, TOPIC_MODULES, canonical_topic


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
        maybe_topic = canonical_topic(parts[consumed])
        if (level, maybe_topic) in TOPIC_MODULES:
            topic = maybe_topic
            consumed += 1
    rest = " ".join(parts[consumed:]).strip()
    return level, topic, rest


async def math_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/math opens the same main menu as /start."""
    await home.start_command(update, context)


async def mathhelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.effective_chat:
        return
    screen = await Screen.load(update, context)
    await update.message.reply_text(math_help_text(), reply_markup=home.home_keyboard(screen))


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
    # The same lesson screen as 📘 Learn, in the student's language.
    await learn.show_lesson(await Screen.load(update, context), topic)


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
    """/practice [level] [topic] [easy|medium|hard]: the same question screen as the ✍️ Practice button."""
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    fallback = await asyncio.to_thread(get_user_level, update.effective_chat.id, update.effective_user.id)
    level, topic, rest = parse_level_topic_text(" ".join(context.args or []), fallback)
    difficulty = normalize_difficulty(rest.split()[0] if rest else "")
    screen = await Screen.load(update, context)
    await practice.new_question(screen, topic, practice.DIFFICULTY_MODE.get(difficulty, practice.AUTO))


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await practice_command(update, context)


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/check answer: the same as typing the answer (one more try, then the solution)."""
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    question = await practice.active_question(update.effective_chat.id, update.effective_user.id)
    if not question:
        await update.message.reply_text("No active practice question. Try /practice high_school algebra")
        return
    answer = " ".join(context.args or []).strip()
    if not answer:
        await update.message.reply_text("Usage: /check your_answer")
        return
    screen = await Screen.load(update, context)
    await practice.handle_answer(screen, question, answer)


async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    report = await asyncio.to_thread(progress_report, update.effective_user.id)
    await update.message.reply_text(report)


async def math_newchat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    deleted = await asyncio.to_thread(
        clear_history, update.effective_chat.id, update.effective_user.id, MATH_MEMORY_TOPICS
    )
    await update.message.reply_text(f"Cleared {deleted} math tutor memory messages." if deleted else "No math tutor memory to clear.")


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
    # Old "math_level:" and "math_action:" buttons are handled by ui/router.py (OLD_BUTTONS).
