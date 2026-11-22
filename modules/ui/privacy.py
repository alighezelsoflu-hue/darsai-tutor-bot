"""🔒 Privacy: the privacy policy, and 🗑 Delete my data.

Routes (⚙️ Settings → 🔒 Privacy, and /privacy, /deletemydata):
    priv        the privacy policy, with 🗑 Delete my data
    priv:d      are you sure?
    priv:d:y    delete everything (modules/privacy.py), and forget the student in this process too

The policy names who receives data from the settings in use: the AI provider (AI_PROVIDER), Sentry when
SENTRY_DSN is set, and the contact line only when PRIVACY_CONTACT is set. When the backup AI provider comes
(Phase 1, step 8), it must be named here too.
"""

import asyncio
import logging
from typing import List, Tuple

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from config import BOT_NAME
from modules import stats
from modules.privacy import delete_student

from . import setup
from .core import Screen
from .practice import owner_line

logger = logging.getLogger(__name__)

# How the AI providers are called in the policy (company names, the same in every language).
AI_PROVIDER_NAMES = {"groq": "Groq", "openrouter": "OpenRouter", "openai": "OpenAI"}


def ai_receivers() -> str:
    provider = config.AI_PROVIDER.lower().strip()
    return AI_PROVIDER_NAMES.get(provider, provider)


def policy_text(screen: Screen) -> str:
    s = screen
    parts = [
        owner_line(s) + s.t("privacy.title", bot=BOT_NAME),
        s.t("privacy.stored"),
        s.t("privacy.not_stored"),
        s.t("privacy.receivers", ai=ai_receivers()) + ("\n" + s.t("privacy.sentry") if config.SENTRY_DSN else ""),
        s.t("privacy.telegram_chat"),
        s.t("privacy.delete"),
    ]
    if config.PRIVACY_CONTACT:
        parts.append(s.t("privacy.contact", contact=config.PRIVACY_CONTACT))
    return "\n\n".join(parts)


def policy_view(screen: Screen) -> Tuple[str, InlineKeyboardMarkup]:
    s = screen
    return policy_text(s), s.keyboard([
        [s.button(s.t("btn.delete_data"), "priv", "d")],
        [s.button(s.t("btn.back_settings"), "set")],
    ])


def confirm_view(screen: Screen) -> Tuple[str, InlineKeyboardMarkup]:
    s = screen
    return owner_line(s) + s.t("delete.confirm"), s.keyboard([
        [s.button(s.t("btn.delete_yes"), "priv", "d", "y")],
        [s.button(s.t("btn.cancel"), "priv")],
    ])


def forget_in_process(update_context, user_id: int) -> None:
    """The per-process caches that hold user ids. A new cache with user ids belongs here too."""
    stats._seen.discard(user_id)
    setup._current.discard(user_id)
    application = getattr(update_context, "application", None)
    if application is not None:
        application.drop_user_data(user_id)


async def delete_everything(screen: Screen) -> None:
    await asyncio.to_thread(delete_student, screen.user_id)
    forget_in_process(screen.context, screen.user_id)
    # The language they used, although it is deleted now. No buttons: they would start new records.
    await screen.show(owner_line(screen) + screen.t("delete.done"))


async def privacy_route(screen: Screen, args: List[str]) -> None:
    if args[:2] == ["d", "y"]:
        await delete_everything(screen)
    elif args[:1] == ["d"]:
        await screen.show(*confirm_view(screen))
    else:
        await screen.show(*policy_view(screen))


async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/privacy (Telegram's "Privacy Policy" in the bot's profile opens it too)."""
    if not update.effective_message or not update.effective_user or not update.effective_chat:
        return
    screen = await Screen.load(update, context)
    await screen.send(*policy_view(screen))


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/deletemydata asks first, like the button."""
    if not update.effective_message or not update.effective_user or not update.effective_chat:
        return
    screen = await Screen.load(update, context)
    await screen.send(*confirm_view(screen))
