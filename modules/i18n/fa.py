"""Persian interface text (casual «تو»). Same keys and {placeholders} as en.py.

Formulas never go in here as plain text inside a sentence: they are added by the code on their own
line with a left-to-right mark, so the right-to-left layout cannot reorder them.
A /command inside a sentence needs a left-to-right mark (\u200e) right before it, or it shows as
"start/". A test checks this.
"""

STRINGS = {
    # Levels
    "level.middle_school": "متوسطه اول",
    "level.high_school": "متوسطه دوم (دهم و یازدهم)",
    "level.pre_college": "دوازدهم و کنکور",
    "level.university": "دانشگاه",

    # /start and the main menu
    "welcome": "به {bot} خوش اومدی 🎓\nفقط جواب نه، یادگیری واقعی.\nهر وقت خواستی، دکمه‌ی «🏠 منو» پایین صفحه رو بزن.",
    "home.text": "منوی اصلی {bot} 🎓\n\nسطح: {level}\nچی کار می‌خوای بکنی؟",
    "home.hint": "از منوی زیر یکی رو انتخاب کن 👇",

    # Buttons
    "btn.learn": "📘 یادگیری",
    "btn.practice": "✍️ تمرین",
    "btn.tutor": "🧑‍🏫 از معلم بپرس",
    "btn.solve": "🧮 حل معادله",
    "btn.plot": "📈 رسم نمودار",
    "btn.progress": "📊 پیشرفت من",
    "btn.settings": "⚙️ تنظیمات",
    "btn.menu": "🏠 منو",
    "btn.back_settings": "🔙 تنظیمات",
    "btn.language": "🌐 زبان",
    "btn.level": "🎓 سطح",
    "btn.clear_memory": "🧹 پاک کردن حافظه‌ی معلم",
    "btn.clear_yes": "آره، پاک کن",
    "btn.cancel": "نه، بی‌خیال",

    # Settings
    "settings.text": "⚙️ تنظیمات\n\nزبان: {language}\nسطح: {level}",
    "language.text": "🌐 زبانت رو انتخاب کن\nربات با همین زبان باهات حرف می‌زنه.",
    "language.changed": "✅ زبان: {language}",
    "level.text": "🎓 سطحت رو انتخاب کن",
    "clear.confirm": "🧹 حافظه‌ی معلم پاک بشه؟\nمعلم گفت‌وگوهای قبلیت توی این چت رو فراموش می‌کنه. پیشرفتت سر جاش می‌مونه.",

    # Pop-up notices (shown briefly at the top of the chat)
    "toast.saved": "✅ ذخیره شد",
    "toast.cleared": "✅ {count} پیام ذخیره‌شده پاک شد",
    "toast.nothing_to_clear": "چیزی برای پاک کردن نبود",
    "toast.coming_soon": "⏳ به‌زودی",
    "toast.not_your_menu": "این منو مال یکی دیگه‌ست. برای منوی خودت \u200e/start رو بفرست.",

    # Telegram's "/" command menu
    "command.start": "منوی اصلی",
    "command.help": "راهنما و همه‌ی دستورها",
}
