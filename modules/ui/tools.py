"""🧑‍🏫 Ask the tutor, 🧮 Solve and 📈 Plot. The student types a question, an equation or a function.

Pressing one of them sets the student's input mode (modules/input_mode.py), so their next typed messages
go there until they press 🏠 Menu or start practising. In groups they reply to the bot's messages instead.

Routes:
    tutor[:<topic>]        ask the tutor (about a topic from Learn, or any math)
    solve                  type equations
    solve:x:<result id>    the tutor explains a solved equation step by step
    plot                   type functions
"""

import asyncio
import secrets
import time
from contextlib import suppress
from typing import Dict, List, Optional, Tuple

from telegram import InlineKeyboardMarkup, InputFile
from telegram.error import BadRequest

from config import FREE_DAILY_AI_LIMIT
from modules.ai import AILimitReached, ask_ai_with_memory, log_ai_error
from modules.common import LANGUAGES
from modules.i18n import local_digits
from modules.input_mode import get_input_mode, set_input_mode, update_input_mode
from modules.math.plot import create_plot, parse_plot_input
from modules.math.prompts import math_tutor_prompt
from modules.math.shared import SolveError, UnsupportedEquation, get_user_level, nice, solve_equation
from modules.math.topics import TOPIC_LEVEL

from .core import Screen
from .practice import formulas, owner_line, topic_name

MODES = ("tutor", "solve", "plot")
# After this long, typed text no longer goes to the tool the student opened.
MODE_MAX_AGE_SECONDS = 24 * 60 * 60
# In groups, replies to the newest of these messages count.
MAX_MESSAGE_IDS = 20
TUTOR_GENERAL_TOPIC = "math"
SOLVE_EXAMPLES = ["2x + 5 = 17", "x^2 - 5x + 6 = 0"]
PLOT_EXAMPLES = ["y = x^2 - 4x + 3", "sin(x)"]
PLOT_RANGE_EXAMPLE = "y = x^2 range -5 5"
# Solver problems that are about how the equation is written: no "Explain" button, but an example.
SOLVE_ERROR_EXAMPLES = {"two_equals": "", "needs_equals": "2x + 5 = 17", "empty_side": "", "no_x": "3*4 + 2"}


def menu_keyboard(screen: Screen) -> InlineKeyboardMarkup:
    return screen.keyboard([[screen.button(screen.t("btn.menu"), "home")]])


def ai_error_text(screen: Screen, error: Exception) -> str:
    """Translated text for a failed tutor request. Details go to the log, never to the student."""
    if isinstance(error, AILimitReached):
        return screen.t("ai.limit", limit=local_digits(screen.lang, FREE_DAILY_AI_LIMIT))
    log_ai_error(error)
    return screen.t("ai.unavailable")


def more_hint(screen: Screen, mode: str) -> str:
    return screen.t(f"{mode}.more" if screen.private else f"{mode}.more_group")


# ------------------------------------------------------------
# Input mode
# ------------------------------------------------------------

async def start_mode(screen: Screen, mode: str, text: str, topic: str = "") -> None:
    """Show the tool's first screen (in the pressed message) and send the student's typing there."""
    if not screen.private:
        text += "\n\n" + screen.t(f"{mode}.reply_hint")
    state = {"id": secrets.token_hex(4), "mode": mode, "topic": topic, "asked_at": time.time()}
    state["message_ids"] = [await screen.show(owner_line(screen) + text, menu_keyboard(screen))]
    await asyncio.to_thread(set_input_mode, screen.chat_id, screen.user_id, state)


async def current_mode(chat_id: int, user_id: int) -> Optional[Dict]:
    """The tool the student's typing goes to in this chat, unless they opened it more than a day ago."""
    state = await asyncio.to_thread(get_input_mode, chat_id, user_id)
    if not state or state.get("mode") not in MODES:
        return None
    if time.time() - float(state.get("asked_at", 0)) > MODE_MAX_AGE_SECONDS:
        return None
    return state


async def remember(screen: Screen, state: Dict, message_id: int) -> None:
    """Save the state with one more of the tool's messages (in groups, replies to it count)."""
    state["message_ids"] = (state.get("message_ids", []) + [message_id])[-MAX_MESSAGE_IDS:]
    await asyncio.to_thread(update_input_mode, screen.chat_id, screen.user_id, state)


async def handle_input(screen: Screen, state: Dict, text: str) -> None:
    handlers = {"tutor": tutor_text, "solve": solve_text, "plot": plot_text}
    await handlers[state["mode"]](screen, state, text.strip())


# ------------------------------------------------------------
# 🧑‍🏫 Ask the tutor
# ------------------------------------------------------------

async def ask_tutor(screen: Screen, topic: str, question: str, prompt_topic: str) -> Optional[str]:
    """The tutor's answer, or None after telling the student why there is none."""
    await screen.typing()
    level = await asyncio.to_thread(get_user_level, screen.chat_id, screen.user_id)
    try:
        return await ask_ai_with_memory(
            chat_id=screen.chat_id,
            user_id=screen.user_id,
            topic=topic,
            user_prompt=question,
            system_prompt=math_tutor_prompt(level, prompt_topic, LANGUAGES[screen.lang]),
            max_tokens=1000,
            temperature=0.22,
        )
    except Exception as error:
        await screen.send(ai_error_text(screen, error), menu_keyboard(screen))
        return None


async def tutor_text(screen: Screen, state: Dict, text: str) -> None:
    topic = state.get("topic") or TUTOR_GENERAL_TOPIC
    answer = await ask_tutor(screen, topic, text, topic)
    if answer is None:
        return
    message_id = await screen.send_long(f"{answer}\n\n{more_hint(screen, 'tutor')}", menu_keyboard(screen))
    await remember(screen, state, message_id)


async def tutor_route(screen: Screen, args: List[str]) -> None:
    topic = args[0] if args and args[0] in TOPIC_LEVEL else ""
    text = screen.t("tutor.text")
    if topic:
        text += "\n" + screen.t("tutor.topic", topic=topic_name(screen, topic))
    await start_mode(screen, "tutor", text, topic)


# ------------------------------------------------------------
# 🧮 Solve
# ------------------------------------------------------------

def solve_view(screen: Screen, equation: str) -> Tuple[str, Optional[str]]:
    """The result for the student, and an English summary for the tutor (None: nothing to explain)."""
    try:
        result = solve_equation(equation)
    except UnsupportedEquation:
        return screen.t("solve.unsupported"), "The bot's solver only handles linear and quadratic equations."
    except SolveError as error:
        if error.code not in SOLVE_ERROR_EXAMPLES:
            return screen.t(f"solve.error.{error.code}"), str(error)
        example = SOLVE_ERROR_EXAMPLES[error.code]
        return screen.t(f"solve.error.{error.code}") + ("\n" + formulas(screen, [example]) if example else ""), None
    except ValueError:
        return screen.t("solve.unreadable") + "\n" + formulas(screen, SOLVE_EXAMPLES[:1]), None

    if result["type"] == "arithmetic":
        value = nice(result["result"])
        return screen.t("solve.result") + "\n" + formulas(screen, [f"{equation} = {value}"]), f"Result: {value}"
    solutions = [f"x = {nice(v)}" for v in result["solutions"]]
    if result["type"] == "linear":
        return screen.t("solve.solution") + "\n" + formulas(screen, solutions), "Linear equation: " + ", ".join(solutions)
    discriminant = nice(result["discriminant"])
    lines = [screen.t("solve.discriminant"), formulas(screen, [f"Δ = b^2 - 4ac = {discriminant}"])]
    if solutions:
        lines += [screen.t("solve.solutions" if len(solutions) > 1 else "solve.solution"), formulas(screen, [", ".join(solutions)])]
        report = f"Quadratic equation. Discriminant = {discriminant}. Solutions: {', '.join(solutions)}"
    else:
        lines.append(screen.t("solve.no_real"))
        report = f"Quadratic equation. Discriminant = {discriminant}. No real solutions."
    return "\n".join(lines), report


async def solve_text(screen: Screen, state: Dict, text: str) -> None:
    body, report = solve_view(screen, text)
    s = screen
    rows = [[s.button(s.t("btn.menu"), "home")]]
    if report is not None:
        result_id = secrets.token_hex(4)
        state["last"] = {"id": result_id, "equation": text, "report": report}
        rows.insert(0, [s.button(s.t("btn.explain"), "solve", "x", result_id)])
    sent = await s.send(f"{body}\n\n{more_hint(s, 'solve')}", s.keyboard(rows))
    await remember(s, state, sent.message_id)


async def explain_solution(screen: Screen, result_id: str) -> None:
    state = await current_mode(screen.chat_id, screen.user_id)
    last = (state or {}).get("last") or {}
    if not state or state["mode"] != "solve" or last.get("id") != result_id:
        await screen.answer(screen.t("toast.expired"))
        return
    # Each result is explained once (the tutor costs one message of the daily limit).
    del state["last"]
    if not await asyncio.to_thread(update_input_mode, screen.chat_id, screen.user_id, state):
        await screen.answer(screen.t("toast.expired"))
        return
    await screen.answer()  # stop the button's spinner before the slow tutor call
    with suppress(BadRequest):
        await screen.query.edit_message_reply_markup(reply_markup=menu_keyboard(screen))
    question = f"Explain this math solution step by step. Problem: {last['equation']}\nResult:\n{last['report']}"
    answer = await ask_tutor(screen, TUTOR_GENERAL_TOPIC, question, "solve")
    if answer is None:
        return
    message_id = await screen.send_long(f"{answer}\n\n{more_hint(screen, 'solve')}", menu_keyboard(screen))
    await remember(screen, state, message_id)


async def solve_route(screen: Screen, args: List[str]) -> None:
    if len(args) > 1 and args[0] == "x":
        await explain_solution(screen, args[1])
        return
    await start_mode(screen, "solve", screen.t("solve.text") + "\n" + formulas(screen, SOLVE_EXAMPLES))


# ------------------------------------------------------------
# 📈 Plot
# ------------------------------------------------------------

async def plot_text(screen: Screen, state: Dict, text: str) -> None:
    try:
        expression, xmin, xmax = parse_plot_input(text)
        image = await asyncio.to_thread(create_plot, expression, xmin, xmax)
    except ValueError:
        examples = [PLOT_EXAMPLES[0], "y = sqrt(x) range 0 10"]
        await screen.send(screen.t("plot.unreadable") + "\n" + formulas(screen, examples), menu_keyboard(screen))
        return
    caption = formulas(screen, [f"y = {expression}"]) + "\n\n" + more_hint(screen, "plot")
    sent = await screen.send_photo(InputFile(image, filename="plot.png"), caption, menu_keyboard(screen))
    await remember(screen, state, sent.message_id)


async def plot_route(screen: Screen, args: List[str]) -> None:
    text = (
        screen.t("plot.text") + "\n" + formulas(screen, PLOT_EXAMPLES) + "\n\n"
        + screen.t("plot.range") + "\n" + formulas(screen, [PLOT_RANGE_EXAMPLE])
    )
    await start_mode(screen, "plot", text)
