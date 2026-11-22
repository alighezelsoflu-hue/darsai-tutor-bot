"""Where typed text goes.

Private chats: the bottom keyboard's 🏠 Menu opens the home screen and leaves any tool, and its ▶️ Continue
does what the home screen's ▶️ Continue does. Otherwise the text goes to the tool the student opened (tutor,
solve, plot), else answers their practice question, else they get a nudge to the menu.

Groups: the bot only sees replies to its own messages (privacy mode). A reply to one of the student's tool
messages goes to that tool, a reply to their practice question is an answer, and anything else is ignored.
"""

import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from modules.input_mode import clear_input_mode

from . import practice, tools
from .core import CONTINUE_LABELS, MENU_LABELS, Screen
from .courses import continue_route
from .home import home_view


async def private_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not update.effective_user or not update.effective_chat:
        return
    screen = await Screen.load(update, context)
    text = message.text or ""
    if text.strip() in MENU_LABELS:
        await asyncio.to_thread(clear_input_mode, screen.chat_id, screen.user_id)
        await screen.send(*await home_view(screen))
        return
    if text.strip() in CONTINUE_LABELS:
        await continue_route(screen, [])
        return
    state = await tools.current_mode(screen.chat_id, screen.user_id)
    if state:
        await tools.handle_input(screen, state, text)
        return
    question = await practice.active_question(screen.chat_id, screen.user_id)
    if question:
        await practice.handle_answer(screen, question, text)
        return
    await screen.send(*await home_view(screen, hint=True))


async def group_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not message.reply_to_message or not update.effective_user or not update.effective_chat:
        return
    chat_id, user_id = update.effective_chat.id, update.effective_user.id
    replied_to = message.reply_to_message.message_id
    state = await tools.current_mode(chat_id, user_id)
    if state and replied_to in state.get("message_ids", []):
        await tools.handle_input(await Screen.load(update, context), state, message.text or "")
        return
    question = await practice.active_question(chat_id, user_id)
    if question and replied_to in question.get("message_ids", []):
        await practice.handle_answer(await Screen.load(update, context), question, message.text or "")
