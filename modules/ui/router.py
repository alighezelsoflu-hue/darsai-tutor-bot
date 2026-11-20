"""Sends button presses and typed text to the right screen."""

from typing import Awaitable, Callable, Dict, List

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from . import home
from .core import CALLBACK_PREFIX, Screen, unpack

Route = Callable[[Screen, List[str]], Awaitable[None]]

# The first part of a button's route picks the screen. The rest is passed to it.
ROUTES: Dict[str, Route] = {
    "home": home.home_route,
    "set": home.settings_route,
}


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user or not update.effective_chat:
        return
    screen = await Screen.load(update, context)
    parsed = unpack(query.data)
    if parsed is None:
        await screen.answer()
        return
    owner_id, route = parsed
    if owner_id != screen.user_id:
        await screen.answer(screen.t("toast.not_your_menu"))
        return
    handler = ROUTES.get(route[0]) if route else None
    if handler is None:
        # A main menu entry that is not built yet.
        await screen.answer(screen.t("toast.coming_soon"))
        return
    try:
        await handler(screen, route[1:])
    finally:
        await screen.answer()


def register_ui_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", home.start_command))
    app.add_handler(CallbackQueryHandler(callback_router, pattern=rf"^{CALLBACK_PREFIX}:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, home.text_message))
