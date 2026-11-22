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
    "btn.show_solution": "💡 راه‌حل رو نشونم بده",
    "btn.skip": "⏭ یه سؤال دیگه",
    "btn.next": "⬅️ سؤال بعدی",
    "btn.easier": "🔽 آسان‌تر",
    "btn.harder": "🔼 سخت‌تر",
    "btn.topics": "📚 موضوع‌ها",

    # Settings
    "settings.text": "⚙️ تنظیمات\n\nزبان: {language}\nسطح: {level}",
    "language.text": "🌐 زبانت رو انتخاب کن\nربات با همین زبان باهات حرف می‌زنه.",
    "language.changed": "✅ زبان: {language}",
    "level.text": "🎓 سطحت رو انتخاب کن",
    "clear.confirm": "🧹 حافظه‌ی معلم پاک بشه؟\nمعلم گفت‌وگوهای قبلیت توی این چت رو فراموش می‌کنه. پیشرفتت سر جاش می‌مونه.",

    # Practice topics and difficulty
    "topic.linear_equations": "معادله‌ی درجه اول",
    "topic.algebra": "معادله‌ی پرانتزدار",
    "topic.quadratics": "معادله‌ی درجه دوم",
    "topic.precalculus": "تابع",
    "topic.calculus": "مشتق",
    "difficulty.easy": "🟢 آسان",
    "difficulty.medium": "🟡 متوسط",
    "difficulty.hard": "🔴 سخت",

    # Practice screens
    "practice.topics": "✍️ تمرین · {level}\n\nیه موضوع انتخاب کن:",
    "practice.topic_progress": "{topic}: {bar} {percent}٪",
    "practice.topic_new": "{topic}: هنوز شروع نکردی",
    "practice.header": "✍️ {topic} · {difficulty}",
    "prompt.solve": "معادله رو حل کن:",
    "prompt.evaluate": "مقدار تابع رو حساب کن:",
    "prompt.derivative": "مشتق تابع رو پیدا کن:",
    "practice.type_answer": "✏️ جوابت رو تایپ کن.",
    "practice.reply_answer": "✏️ روی همین پیام ریپلای کن و جوابت رو بنویس.",
    "practice.two_answers": "دو تا جواب داره. با ویرگول جداشون کن، مثلاً:",
    "practice.correct": "✅ درسته!",
    "practice.correct_second": "✅ درسته! این بار درست زدی.",
    "practice.try_again": "❌ نه، این نشد. یه بار دیگه امتحان کن!",
    "practice.type_again": "✏️ جواب جدیدت رو تایپ کن.",
    "practice.reply_again": "✏️ روی همین پیام ریپلای کن و جواب جدیدت رو بنویس.",
    "practice.missed": "❌ این بار نشد. اشکالی نداره، با اشتباه یاد می‌گیریم.",
    "practice.solution": "💡 راه‌حل:",
    "practice.mastery": "📊 {topic}: {bar} {percent}٪{change}",
    "practice.next_harder": "🔥 عالیه! سؤال‌های بعدی: {difficulty}",
    "practice.next_easier": "🙂 بیا دوباره قدم‌به‌قدم بریم جلو. سؤال‌های بعدی: {difficulty}",
    "practice.unreadable": "🤔 این رو نتونستم به‌عنوان جواب بخونم.\nیه عدد یا عبارت بنویس، مثلاً:",

    # Solution steps (formulas are added by the code on the next line)
    "step.add": "{n} رو به دو طرف اضافه کن:",
    "step.subtract": "{n} رو از دو طرف کم کن:",
    "step.divide": "دو طرف رو بر {n} تقسیم کن:",
    "step.expand": "پرانتز رو باز کن:",
    "step.x_one_side": "جمله‌های مجهول‌دار رو ببر یه طرف:",
    "step.factor": "تجزیه‌ش کن:",
    "step.zero_factors": "هر کدوم از عامل‌ها می‌تونه صفر باشه، پس:",
    "step.substitute": "عدد رو توی تابع جایگذاری کن:",
    "step.calculate": "حساب کن:",
    "step.terms": "هر جمله رو جدا حساب کن:",
    "step.add_up": "با هم جمعشون کن:",
    "step.power_rule": "از قاعده‌ی مشتق توان استفاده کن:",
    "step.so": "پس:",
    "step.each_term": "از هر جمله جدا مشتق بگیر. مشتق عدد ثابت صفره:",

    # Pop-up notices (shown briefly at the top of the chat)
    "toast.saved": "✅ ذخیره شد",
    "toast.cleared": "✅ {count} پیام ذخیره‌شده پاک شد",
    "toast.nothing_to_clear": "چیزی برای پاک کردن نبود",
    "toast.coming_soon": "⏳ به‌زودی",
    "toast.not_your_menu": "این منو مال یکی دیگه‌ست. برای منوی خودت \u200e/start رو بفرست.",
    "toast.question_over": "این سؤال دیگه تموم شده.",

    # Telegram's "/" command menu
    "command.start": "منوی اصلی",
    "command.help": "راهنما و همه‌ی دستورها",
}
