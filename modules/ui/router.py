"""Sends button presses and typed text to the right screen."""

import re
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import groups, home, learn, practice, premium, progress, tools, typed
from .core import CALLBACK_PREFIX, Screen, unpack

Route = Callable[[Screen, List[str]], Awaitable[None]]

# The first part of a button's route picks the screen. The rest is passed to it.
ROUTES: Dict[str, Route] = {
    "home": home.home_route,
    "set": home.settings_route,
    "prac": practice.practice_route,
    "learn": learn.learn_route,
    "tutor": tools.tutor_route,
    "solve": tools.solve_route,
    "plot": tools.plot_route,
    "prog": progress.progress_route,
    "prem": premium.premium_route,
}

# Buttons from before the button interface, still in old messages (and "menu:math" from /aihelp).
# They have no owner, so they open the new screen for whoever presses them.
OLD_BUTTONS: Dict[str, Tuple[str, ...]] = {
    "menu:math": ("home",),
    "main:level": ("set", "lvl"),
    "main:practice": ("prac",),
    "main:plot": ("plot",),
    "main:ai": ("tutor",),
    "main:progress": ("prog",),
    "main:subscribe": ("prem",),
    "math_action:tutor": ("tutor",),
    "math_action:practice": ("prac",),
    "math_action:plot": ("plot",),
    "math_action:progress": ("prog",),
}
OLD_LEVEL_PREFIX = "math_level:"  # math_level:<level> saves the level
OLD_BUTTON_PATTERN = "^(?:" + "|".join(re.escape(data) for data in OLD_BUTTONS) + f"|{OLD_LEVEL_PREFIX}.*)$"


def old_route(data: Optional[str]) -> Optional[List[str]]:
    data = data or ""
    if data in OLD_BUTTONS:
        return list(OLD_BUTTONS[data])
    if data.startswith(OLD_LEVEL_PREFIX):
        return ["set", "lvl", data[len(OLD_LEVEL_PREFIX):]]
    return None


async def dispatch(screen: Screen, route: List[str]) -> None:
    handler = ROUTES.get(route[0]) if route else None
    if handler is None:
        # A main menu entry that is not built yet.
        await screen.answer(screen.t("toast.coming_soon"))
        return
    try:
        await handler(screen, route[1:])
    finally:
        await screen.answer()


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user or not update.effective_chat:
        return
    screen = await Screen.load(update, context)
    parsed = unpack(query.data)
    if parsed is None:
        await screen.answer(screen.t("toast.old_button"))
        return
    owner_id, route = parsed
    if owner_id != screen.user_id:
        await screen.answer(screen.t("toast.not_your_menu"))
        return
    await dispatch(screen, route)


async def old_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query or not update.effective_user or not update.effective_chat:
        return
    await dispatch(await Screen.load(update, context), old_route(update.callback_query.data) or [])


async def unknown_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Any button no other handler knows. Answer it, or Telegram shows a spinner until it times out."""
    if not update.callback_query or not update.effective_user or not update.effective_chat:
        return
    screen = await Screen.load(update, context)
    await screen.answer(screen.t("toast.old_button"))


def register_ui_handlers(app: Application) -> None:
    # Before everything else: posts sent as the group or as a channel have no real student behind them.
    app.add_handler(
        MessageHandler(
            filters.SenderChat.ALL & ~filters.IS_AUTOMATIC_FORWARD & (filters.COMMAND | filters.REPLY),
            groups.anonymous_sender,
        ),
        group=-1,
    )
    app.add_handler(CommandHandler("start", home.start_command))
    app.add_handler(CommandHandler("subscribe", premium.subscribe_command))
    app.add_handler(CallbackQueryHandler(callback_router, pattern=rf"^{CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(old_button, pattern=OLD_BUTTON_PATTERN))
    app.add_handler(ChatMemberHandler(groups.bot_added, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, typed.private_text))
    # In groups the bot only sees replies to its own messages (privacy mode).
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS & filters.REPLY, typed.group_reply))


def register_fallback_handlers(app: Application) -> None:
    """Call last: catches buttons that no handler registered before it knows."""
    app.add_handler(CallbackQueryHandler(unknown_button))
