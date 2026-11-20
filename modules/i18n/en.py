"""English interface text. fa.py must have exactly the same keys and {placeholders}."""

STRINGS = {
    # Levels
    "level.middle_school": "Middle School",
    "level.high_school": "High School",
    "level.pre_college": "Pre-College",
    "level.university": "University",

    # /start and the main menu
    "welcome": "Welcome to {bot} 🎓\nNot just answers. Real learning.\nTap the 🏠 Menu button at the bottom any time.",
    "home.text": "{bot} 🎓\n\nLevel: {level}\nWhat would you like to do?",
    "home.hint": "Pick something from the menu below 👇",

    # Buttons
    "btn.learn": "📘 Learn",
    "btn.practice": "✍️ Practice",
    "btn.tutor": "🧑‍🏫 Ask the tutor",
    "btn.solve": "🧮 Solve",
    "btn.plot": "📈 Plot",
    "btn.progress": "📊 My progress",
    "btn.settings": "⚙️ Settings",
    "btn.menu": "🏠 Menu",
    "btn.back_settings": "🔙 Settings",
    "btn.language": "🌐 Language",
    "btn.level": "🎓 Level",
    "btn.clear_memory": "🧹 Clear tutor memory",
    "btn.clear_yes": "Yes, clear it",
    "btn.cancel": "Cancel",

    # Settings
    "settings.text": "⚙️ Settings\n\nLanguage: {language}\nLevel: {level}",
    "language.text": "🌐 Choose your language\nThe bot will talk to you in this language.",
    "language.changed": "✅ Language: {language}",
    "level.text": "🎓 Choose your level",
    "clear.confirm": "🧹 Clear the tutor's memory?\nThe tutor will forget your earlier conversations in this chat. Your progress is kept.",

    # Pop-up notices (shown briefly at the top of the chat)
    "toast.saved": "✅ Saved",
    "toast.cleared": "✅ Cleared {count} saved messages",
    "toast.nothing_to_clear": "Nothing to clear",
    "toast.coming_soon": "⏳ Coming soon",
    "toast.not_your_menu": "This menu belongs to someone else. Send /start to get your own.",

    # Telegram's "/" command menu
    "command.start": "Open the main menu",
    "command.help": "Help and all commands",
}
