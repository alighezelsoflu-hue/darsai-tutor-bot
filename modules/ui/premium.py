"""💎 Premium: what it will add, and what the student would want most from it (the waitlist).

Premium isn't built yet. The screen says so honestly and asks the student to pick what they'd want most
(as many as they like). Each pick is saved right away (modules/premium.py) and /stats counts them.

The daily-limit message offers the same picks to students who haven't picked anything yet.

Routes:
    prem                       the Premium screen (also /subscribe and the old "main:subscribe" button)
    prem:a:<choice>:<where>    add a pick       where: m = on the Premium screen, l = on the daily-limit message
    prem:r:<choice>:<where>    remove a pick
Each button says what it does, so a button on an older message still does what its label shows.
"""

import asyncio
from typing import List, Tuple

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import BOT_NAME, FREE_DAILY_AI_LIMIT
from modules.i18n import local_digits
from modules.premium import CHOICES, get_choices, set_choice

from .core import Screen
from .practice import owner_line

# Where a pick was made: the code in the button's route, and the name saved with the pick.
WHERE = {"m": "menu", "l": "limit"}


def choice_keyboard(screen: Screen, picks: List[str], where: str) -> InlineKeyboardMarkup:
    """One button per choice (✓ when picked; pressing it again removes it), then 🏠 Menu."""
    s = screen
    rows = []
    for choice in CHOICES:
        picked = choice in picks
        label = s.t(f"premium.choice.{choice}") + (" ✓" if picked else "")
        rows.append([s.button(label, "prem", "r" if picked else "a", choice, where)])
    rows.append([s.button(s.t("btn.menu"), "home")])
    return s.keyboard(rows)


def premium_text(screen: Screen, picks: List[str]) -> str:
    s = screen
    if FREE_DAILY_AI_LIMIT > 0:
        free = s.t("premium.free_now", limit=local_digits(s.lang, FREE_DAILY_AI_LIMIT))
    else:
        free = s.t("premium.free_now_unlimited")
    features = "\n".join(s.t(f"premium.feature.{name}") for name in ("messages", "photo", "guide", "report"))
    parts = [
        owner_line(s) + s.t("premium.title", bot=BOT_NAME),
        s.t("premium.intro") + "\n" + features,
        free + "\n" + s.t("premium.question"),
    ]
    if picks:
        parts.append(s.t("premium.thanks"))
    return "\n\n".join(parts)


def limit_text(screen: Screen) -> str:
    return screen.t("ai.limit", limit=local_digits(screen.lang, FREE_DAILY_AI_LIMIT))


def limit_offer(screen: Screen, picks: List[str]) -> Tuple[str, InlineKeyboardMarkup]:
    """The daily-limit message with the Premium picks under it."""
    parts = [owner_line(screen) + limit_text(screen), screen.t("ai.limit_offer")]
    if picks:
        parts.append(screen.t("premium.thanks"))
    return "\n\n".join(parts), choice_keyboard(screen, picks, "l")


async def limit_view(screen: Screen) -> Tuple[str, InlineKeyboardMarkup]:
    """What a student sees when they have no tutor messages left today.

    Students who already picked something get the plain message, so they aren't asked again every day.
    """
    picks = await asyncio.to_thread(get_choices, screen.user_id)
    if picks:
        return owner_line(screen) + limit_text(screen), screen.keyboard([[screen.button(screen.t("btn.menu"), "home")]])
    return limit_offer(screen, picks)


async def show_premium(screen: Screen) -> None:
    picks = await asyncio.to_thread(get_choices, screen.user_id)
    await screen.show(premium_text(screen, picks), choice_keyboard(screen, picks, "m"))


async def change_pick(screen: Screen, action: str, choice: str, where: str) -> None:
    if action not in ("a", "r") or choice not in CHOICES or where not in WHERE:
        await screen.answer(screen.t("toast.expired"))
        return
    picks = await asyncio.to_thread(set_choice, screen.user_id, choice, action == "a", WHERE[where], screen.lang)
    await screen.answer(screen.t("toast.premium_thanks" if action == "a" else "toast.removed"))
    if where == "l":
        await screen.show(*limit_offer(screen, picks))
    else:
        await screen.show(premium_text(screen, picks), choice_keyboard(screen, picks, "m"))


async def premium_route(screen: Screen, args: List[str]) -> None:
    if len(args) >= 3:
        await change_pick(screen, args[0], args[1], args[2])
    else:
        await show_premium(screen)


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/subscribe opens the Premium screen."""
    if not update.effective_message or not update.effective_user or not update.effective_chat:
        return
    await show_premium(await Screen.load(update, context))
