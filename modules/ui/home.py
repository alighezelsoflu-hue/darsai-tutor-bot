"""/start, the main menu and the Settings screens."""

import asyncio
from typing import List, Tuple

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import BOT_NAME
from modules.ai import clear_history
from modules.i18n import LANGUAGE_NAMES, UI_LANGUAGES, level_label, local_digits
from modules.math.shared import get_user_level, set_user_level
from modules.student import set_language

from .core import MENU_LABELS, Screen, menu_reply_keyboard

LEVEL_ORDER = ("middle_school", "high_school", "pre_college", "university")


# ------------------------------------------------------------
# Main menu
# ------------------------------------------------------------

def home_keyboard(screen: Screen) -> InlineKeyboardMarkup:
    s = screen
    return s.keyboard([
        [s.button(s.t("btn.learn"), "learn"), s.button(s.t("btn.practice"), "prac")],
        [s.button(s.t("btn.tutor"), "tutor"), s.button(s.t("btn.solve"), "solve")],
        [s.button(s.t("btn.plot"), "plot"), s.button(s.t("btn.progress"), "prog")],
        [s.button(s.t("btn.settings"), "set")],
    ])


async def home_view(screen: Screen, hint: bool = False) -> Tuple[str, InlineKeyboardMarkup]:
    level = await asyncio.to_thread(get_user_level, screen.chat_id, screen.user_id)
    parts: List[str] = []
    if hint:
        parts.append(screen.t("home.hint"))
    if not screen.private:
        # In a group, say whose menu this is.
        parts.append(f"👤 {screen.user.first_name}")
    parts.append(screen.t("home.text", bot=BOT_NAME, level=level_label(screen.lang, level)))
    return "\n\n".join(parts), home_keyboard(screen)


async def home_route(screen: Screen, args: List[str]) -> None:
    text, markup = await home_view(screen)
    await screen.show(text, markup)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_user or not update.effective_chat:
        return
    screen = await Screen.load(update, context)
    if screen.private:
        # A separate message, because one message can't carry both the bottom Menu button and inline buttons.
        await update.effective_message.reply_text(
            screen.t("welcome", bot=BOT_NAME), reply_markup=menu_reply_keyboard(screen.lang)
        )
    text, markup = await home_view(screen)
    await screen.send(text, markup)


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Typed text in a private chat. For now: the Menu button, or a nudge towards the menu."""
    message = update.effective_message
    if not message or not update.effective_user or not update.effective_chat:
        return
    screen = await Screen.load(update, context)
    pressed_menu = (message.text or "").strip() in MENU_LABELS
    text, markup = await home_view(screen, hint=not pressed_menu)
    await screen.send(text, markup)


# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

async def show_settings(screen: Screen) -> None:
    level = await asyncio.to_thread(get_user_level, screen.chat_id, screen.user_id)
    s = screen
    text = s.t("settings.text", language=LANGUAGE_NAMES[s.lang], level=level_label(s.lang, level))
    markup = s.keyboard([
        [s.button(s.t("btn.language"), "set", "lang"), s.button(s.t("btn.level"), "set", "lvl")],
        [s.button(s.t("btn.clear_memory"), "set", "clr")],
        [s.button(s.t("btn.menu"), "home")],
    ])
    await s.show(text, markup)


async def show_language_picker(screen: Screen) -> None:
    s = screen
    buttons = [
        s.button(LANGUAGE_NAMES[code] + (" ✓" if code == s.lang else ""), "set", "lang", code)
        for code in UI_LANGUAGES
    ]
    await s.show(s.t("language.text"), s.keyboard([buttons, [s.button(s.t("btn.back_settings"), "set")]]))


async def show_level_picker(screen: Screen) -> None:
    s = screen
    current = await asyncio.to_thread(get_user_level, s.chat_id, s.user_id)
    buttons = [
        s.button(level_label(s.lang, level) + (" ✓" if level == current else ""), "set", "lvl", level)
        for level in LEVEL_ORDER
    ]
    # One per row: some level names are too long for half a phone screen.
    rows = [[button] for button in buttons]
    rows.append([s.button(s.t("btn.back_settings"), "set")])
    await s.show(s.t("level.text"), s.keyboard(rows))


async def change_language(screen: Screen, language: str) -> None:
    await asyncio.to_thread(set_language, screen.user_id, language)
    screen.lang = language
    await screen.answer(screen.t("toast.saved"))
    await show_settings(screen)
    if screen.private:
        # The bottom Menu button only changes when a message carries the new keyboard.
        await screen.context.bot.send_message(
            screen.chat_id,
            screen.t("language.changed", language=LANGUAGE_NAMES[language]),
            reply_markup=menu_reply_keyboard(language),
        )


async def clear_memory(screen: Screen) -> None:
    deleted = await asyncio.to_thread(clear_history, screen.chat_id, screen.user_id, (), True)
    if deleted:
        await screen.answer(screen.t("toast.cleared", count=local_digits(screen.lang, deleted)))
    else:
        await screen.answer(screen.t("toast.nothing_to_clear"))
    await show_settings(screen)


async def settings_route(screen: Screen, args: List[str]) -> None:
    """Routes: set | set:lang[:<code>] | set:lvl[:<level>] | set:clr[:y]"""
    action = args[0] if args else ""
    choice = args[1] if len(args) > 1 else ""
    if action == "lang":
        if choice in UI_LANGUAGES:
            await change_language(screen, choice)
        else:
            await show_language_picker(screen)
    elif action == "lvl":
        if choice in LEVEL_ORDER:
            await asyncio.to_thread(set_user_level, screen.chat_id, screen.user_id, choice)
            await screen.answer(screen.t("toast.saved"))
            await show_settings(screen)
        else:
            await show_level_picker(screen)
    elif action == "clr":
        if choice == "y":
            await clear_memory(screen)
        else:
            s = screen
            await s.show(s.t("clear.confirm"), s.keyboard([
                [s.button(s.t("btn.clear_yes"), "set", "clr", "y"), s.button(s.t("btn.cancel"), "set")],
            ]))
    else:
        await show_settings(screen)
