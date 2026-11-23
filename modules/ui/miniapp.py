"""📚 The Mini App in the chat. Step 1 (the reachability test) is for testers only: the admins (ADMIN_USER_IDS) and
MINIAPP_TESTER_IDS. Everyone else keeps the default menu button and gets no reply to /app.

- setup_menu_buttons(): at startup, each tester's chat gets a "📚 DarsAI" menu button next to the message box
  that opens MINIAPP_URL (setChatMenuButton per chat). A tester who never started the bot is only logged.
- /app (testers, private chats): sets the tester's menu button too, and sends 📚 Open the app plus
  "❌ It didn't open", so an app that never loads is counted as well (route app:x).

The page and its API are in modules/webapp.py; the measurements in modules/miniapp.py.
"""

import asyncio
import logging
from typing import List

from telegram import InlineKeyboardButton, MenuButtonWebApp, Update, WebAppInfo
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

import config
from modules.i18n import t
from modules.miniapp import record_failure

from .core import Screen, student_language

logger = logging.getLogger(__name__)


def testers() -> frozenset:
    return frozenset(config.ADMIN_USER_IDS) | frozenset(config.MINIAPP_TESTER_IDS)


def app_url() -> str:
    """The page's address, or "" when the Mini App is off (Telegram only opens HTTPS pages)."""
    url = config.MINIAPP_URL
    return url if url.startswith("https://") else ""


def menu_button(lang: str) -> MenuButtonWebApp:
    return MenuButtonWebApp(text=t(lang, "app.menu_button"), web_app=WebAppInfo(url=app_url()))


async def set_menu_button(bot, user_id: int, lang: str) -> bool:
    try:
        await bot.set_chat_menu_button(chat_id=user_id, menu_button=menu_button(lang))
        return True
    except TelegramError as error:
        # E.g. the tester hasn't started the bot yet: /app sets it later.
        logger.warning("Could not set the 📚 menu button for tester %s: %s", user_id, error)
        return False


async def setup_menu_buttons(bot) -> List[int]:
    """At startup: the 📚 menu button for every tester. Returns the testers it was set for."""
    if not app_url():
        if config.MINIAPP_URL:
            logger.warning("MINIAPP_URL must start with https:// (Telegram only opens HTTPS pages); the 📚 button is off.")
        return []
    done = []
    for user_id in sorted(testers()):
        lang = await asyncio.to_thread(student_language, user_id, None)
        if await set_menu_button(bot, user_id, lang):
            done.append(user_id)
    logger.info("📚 Mini App at %s: menu button set for %d of %d tester(s).", app_url(), len(done), len(testers()))
    return done


async def app_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/app: testers only, in a private chat. Anyone else gets no reply (like the admin commands)."""
    message, user, chat = update.effective_message, update.effective_user, update.effective_chat
    if not message or not user or not chat:
        return
    if user.id not in testers() or chat.type != ChatType.PRIVATE:
        logger.info("Ignored /app from user id %s in a %s chat (testers only, in a private chat).", user.id, chat.type)
        return
    screen = await Screen.load(update, context)
    if not app_url():
        await message.reply_text(screen.t("app.unavailable"))
        return
    await set_menu_button(context.bot, user.id, screen.lang)
    s = screen
    markup = s.keyboard([
        [InlineKeyboardButton(s.t("btn.app_open"), web_app=WebAppInfo(url=app_url()))],
        [s.button(s.t("btn.app_failed"), "app", "x")],
    ])
    await message.reply_text(s.t("app.command"), reply_markup=markup)


async def app_route(screen: Screen, args: List[str]) -> None:
    """app:x: "❌ It didn't open"."""
    if args[:1] == ["x"] and screen.user_id in testers():
        await asyncio.to_thread(record_failure, screen.user_id)
        await screen.answer(screen.t("toast.app_failed"))
    else:
        await screen.answer(screen.t("toast.expired"))
