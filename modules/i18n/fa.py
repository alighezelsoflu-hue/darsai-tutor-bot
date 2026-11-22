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
    "btn.premium": "💎 پریمیوم",
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
    "btn.practice_topic": "✍️ تمرین همین موضوع",
    "btn.practice_named": "✍️ تمرین: {topic}",
    "btn.learn_topics": "📚 درس‌ها",
    "btn.explain": "🧑‍🏫 توضیح قدم‌به‌قدم",

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

    # Learn
    "learn.topics": "📘 یادگیری · {level}\n\nیه موضوع انتخاب کن:",
    "learn.example": "📝 مثال:",
    "lesson.linear_equations.idea": "معادله‌ی درجه اول یه مجهول داره و بزرگ‌ترین توان مجهولش یکه. برای حلش باید مجهول رو یه طرف تنها کنی.",
    "lesson.linear_equations.rule": "قانون طلایی: هر کاری با یه طرف معادله می‌کنی، با طرف دیگه هم بکن.",
    "lesson.algebra.idea": "وقتی مجهول توی پرانتزه، می‌تونی اول دو طرف رو بر عدد پشت پرانتز تقسیم کنی، یا پرانتز رو باز کنی.",
    "lesson.algebra.expand": "برای باز کردن پرانتز، عدد پشتش رو در همه‌ی جمله‌های داخلش ضرب کن:",
    "lesson.quadratics.idea": "توی معادله‌ی درجه دوم، بزرگ‌ترین توان مجهول دوئه. شکل استانداردش اینه:",
    "lesson.quadratics.factor": "اگه بشه تجزیه‌ش کرد، از این استفاده کن: وقتی حاصل‌ضرب صفره، یکی از عامل‌ها باید صفر باشه.",
    "lesson.quadratics.formula": "وگرنه از روش دلتا استفاده کن:",
    "lesson.precalculus.idea": "تابع یه عدد می‌گیره و دقیقاً یه مقدار برمی‌گردونه. مثلاً:",
    "lesson.precalculus.value": "برای پیدا کردن مقدار تابع توی یه عدد، اون عدد رو جای مجهول بذار و حساب کن.",
    "lesson.calculus.idea": "مشتق نشون می‌ده تابع با چه سرعتی تغییر می‌کنه: یعنی شیب نمودارش توی هر نقطه.",
    "step.check": "برای اطمینان، جواب رو بذار توی معادله:",

    # Ask the tutor
    "tutor.text": "🧑‍🏫 از معلم بپرس\n\nسؤال ریاضیت رو بنویس تا قدم‌به‌قدم برات توضیح بدم.",
    "tutor.topic": "موضوع: {topic}",
    "tutor.reply_hint": "✏️ روی همین پیام ریپلای کن و سؤالت رو بنویس.",
    "tutor.more": "✏️ سؤال دیگه‌ای داری؟ بنویس، یا «🏠 منو» رو بزن.",
    "tutor.more_group": "✏️ برای سؤال بعدی روی همین پیام ریپلای کن.",
    "ai.limit": "⏳ امروز از همه‌ی {limit} پیامی که می‌شد از معلم بپرسی استفاده کردی. ساعت ۳:۳۰ بامداد به وقت تهران دوباره شارژ می‌شه. تمرین، یادگیری، حل معادله و رسم نمودار هنوز کار می‌کنن.",
    "ai.limit_offer": "💎 اشتراک ویژه به‌زودی میاد و باهاش می‌تونی هر روز بیشتر از معلم بپرسی. بیشتر از همه دوست داری چی داشته باشه؟ هر چند تا که می‌خوای انتخاب کن:",
    "ai.unavailable": "😕 معلم الان در دسترس نیست. چند دقیقه دیگه دوباره امتحان کن.",

    # Solve
    "solve.text": "🧮 حل معادله\n\nیه معادله بنویس تا حلش کنم، مثلاً:",
    "solve.reply_hint": "✏️ روی همین پیام ریپلای کن و معادله‌ت رو بنویس.",
    "solve.more": "✏️ معادله‌ی دیگه‌ای داری؟ بنویس، یا «🏠 منو» رو بزن.",
    "solve.more_group": "✏️ برای معادله‌ی بعدی روی همین پیام ریپلای کن.",
    "solve.result": "✅ حاصل:",
    "solve.solution": "✅ جواب:",
    "solve.solutions": "✅ جواب‌ها:",
    "solve.discriminant": "دلتا:",
    "solve.no_real": "❌ جواب حقیقی نداره، چون دلتا منفیه.",
    "solve.unsupported": "🤔 خودم فقط معادله‌ی درجه اول و دوم رو حل می‌کنم. برای این یکی «🧑‍🏫 توضیح قدم‌به‌قدم» رو بزن تا معلم کمکت کنه.",
    "solve.one_per_message": "✏️ هر بار فقط یه معادله بفرست، مثلاً:",
    "solve.unreadable": "🤔 این معادله رو نتونستم بخونم. این شکلی بنویسش:",
    "solve.error.two_equals": "🤔 یه معادله با فقط یه علامت مساوی بنویس.",
    "solve.error.needs_equals": "🤔 برای پیدا کردن مجهول، یه معادله با علامت مساوی بنویس، مثلاً:",
    "solve.error.empty_side": "🤔 هر دو طرف معادله باید یه چیزی داشته باشن.",
    "solve.error.no_x": "🤔 مجهولی برای پیدا کردن نیست. برای حساب کردن، علامت مساوی رو ننویس، مثلاً:",
    "solve.error.no_solution": "❌ این معادله جواب نداره.",
    "solve.error.every_x": "✅ این معادله به ازای هر مقداری از مجهول درسته.",

    # Plot
    "plot.text": "📈 رسم نمودار\n\nیه تابع بنویس تا نمودارش رو بکشم، مثلاً:",
    "plot.range": "برای انتخاب بازه‌ی محور افقی، اینو آخرش اضافه کن:",
    "plot.reply_hint": "✏️ روی همین پیام ریپلای کن و تابعت رو بنویس.",
    "plot.more": "✏️ تابع دیگه‌ای داری؟ بنویس، یا «🏠 منو» رو بزن.",
    "plot.more_group": "✏️ برای تابع بعدی روی همین پیام ریپلای کن.",
    "plot.one_per_message": "✏️ هر بار فقط یه تابع بفرست، مثلاً:",
    "plot.unreadable": "🤔 نتونستم اینو رسم کنم. تابع و بازه رو چک کن، مثلاً:",

    # My progress
    "progress.title": "📊 پیشرفت من",
    "progress.empty": "هنوز تمرین نکردی. چند تا سؤال جواب بده تا تسلطت اینجا نشون داده بشه.",
    "progress.topic": "{topic}: {bar} {percent}٪\n✅ {correct} · ❌ {wrong}",
    "progress.suggest": "💡 پیشنهاد بعدی: {topic}",

    # 💎 Premium. The button says «پریمیوم»; longer text says «اشتراک ویژه».
    "premium.title": "💎 اشتراک ویژه‌ی {bot}",
    "premium.intro": "اشتراک ویژه هنوز آماده نیست. داریم روش کار می‌کنیم و این‌ها رو بهت می‌ده:",
    "premium.feature.messages": "• 🧑‍🏫 پیام بیشتر به معلم در هر روز",
    "premium.feature.photo": "• 📷 حل سؤال از روی عکس: از سؤالت عکس بگیر و بفرست",
    "premium.feature.guide": "• 🧭 «راهنمایی‌م کن»: معلم جواب رو نمی‌گه. هر بار یه سؤال می‌پرسه، هر قدمی که می‌فرستی رو چک می‌کنه و دقیقاً نشون می‌ده اشتباه توی کدوم قدمه.",
    "premium.feature.report": "• 📅 گزارش هفتگی پیشرفتت",
    "premium.free_now": "فعلاً همه‌ی بخش‌های منو رایگانه (معلم محدودیت روزانه‌ی {limit} پیام داره).",
    "premium.free_now_unlimited": "فعلاً همه‌ی بخش‌های منو رایگانه.",
    "premium.question": "بیشتر از همه دوست داری اشتراک ویژه چی داشته باشه؟ هر چند تا که می‌خوای انتخاب کن:",
    "premium.thanks": "🙏 مرسی! انتخاب‌هات ذخیره شد و وقتی اشتراک ویژه آماده شد، خبرت می‌کنم. برای برداشتن یه انتخاب، دوباره روش بزن.",
    "premium.choice.konkur": "🎯 آمادگی کنکور",
    "premium.choice.msgs": "🧑‍🏫 پیام بیشتر به معلم",
    "premium.choice.photo": "📷 حل سؤال از روی عکس",
    "premium.choice.plan": "📊 برنامه‌ی مطالعه و گزارش هفتگی",

    # Pop-up notices (shown briefly at the top of the chat)
    "toast.saved": "✅ ذخیره شد",
    "toast.premium_thanks": "🙏 مرسی!",
    "toast.removed": "برداشته شد",
    "toast.cleared": "✅ {count} پیام ذخیره‌شده پاک شد",
    "toast.nothing_to_clear": "چیزی برای پاک کردن نبود",
    "toast.coming_soon": "⏳ به‌زودی",
    "toast.not_your_menu": "این منو مال یکی دیگه‌ست. برای منوی خودت \u200e/start رو بفرست.",
    "toast.question_over": "این سؤال دیگه تموم شده.",
    "toast.expired": "این دکمه دیگه کار نمی‌کنه.",
    "toast.old_button": "این دکمه مال نسخه‌ی قدیمیه. برای منو \u200e/start رو بفرست.",

    # Group chats
    "group.welcome": "👋 سلام، من {bot} هستم! هر کسی می‌تونه \u200e/start رو بفرسته تا منوی خودش رو بگیره. برای جواب دادن به سؤال‌هام، روی پیام‌های من ریپلای کنین.",
    "group.anonymous": "😶 داری ناشناس یا از طرف یه کانال پیام می‌دی، برای همین نمی‌دونم کی هستی. برای استفاده از {bot}، «ناشناس ماندن» رو خاموش کن یا با حساب خودت پیام بده.",
    "error.generic": "😕 ببخشید، یه مشکلی پیش اومد. دوباره امتحان کن.",

    # Telegram's "/" command menu
    "command.start": "منوی اصلی",
    "command.help": "راهنما و همه‌ی دستورها",
}
