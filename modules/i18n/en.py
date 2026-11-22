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
    "btn.show_solution": "💡 Show solution",
    "btn.skip": "⏭ Skip",
    "btn.next": "➡️ Next question",
    "btn.easier": "🔽 Easier",
    "btn.harder": "🔼 Harder",
    "btn.topics": "📚 Topics",

    # Settings
    "settings.text": "⚙️ Settings\n\nLanguage: {language}\nLevel: {level}",
    "language.text": "🌐 Choose your language\nThe bot will talk to you in this language.",
    "language.changed": "✅ Language: {language}",
    "level.text": "🎓 Choose your level",
    "clear.confirm": "🧹 Clear the tutor's memory?\nThe tutor will forget your earlier conversations in this chat. Your progress is kept.",

    # Practice topics and difficulty
    "topic.linear_equations": "Linear equations",
    "topic.algebra": "Equations with brackets",
    "topic.quadratics": "Quadratic equations",
    "topic.precalculus": "Functions",
    "topic.calculus": "Derivatives",
    "difficulty.easy": "🟢 Easy",
    "difficulty.medium": "🟡 Medium",
    "difficulty.hard": "🔴 Hard",

    # Practice screens
    "practice.topics": "✍️ Practice · {level}\n\nPick a topic:",
    "practice.topic_progress": "{topic}: {bar} {percent}%",
    "practice.topic_new": "{topic}: not started yet",
    "practice.header": "✍️ {topic} · {difficulty}",
    "prompt.solve": "Solve for x:",
    "prompt.evaluate": "Find the value:",
    "prompt.derivative": "Find the derivative:",
    "practice.type_answer": "✏️ Type your answer.",
    "practice.reply_answer": "✏️ Reply to this message with your answer.",
    "practice.two_answers": "There are two answers. Separate them with a comma, for example:",
    "practice.correct": "✅ Correct!",
    "practice.correct_second": "✅ Correct on the second try!",
    "practice.try_again": "❌ Not quite. Try once more!",
    "practice.type_again": "✏️ Type your new answer.",
    "practice.reply_again": "✏️ Reply to this message with your new answer.",
    "practice.missed": "❌ Not this time. That's okay, mistakes are how we learn.",
    "practice.solution": "💡 How to solve it:",
    "practice.mastery": "📊 {topic}: {bar} {percent}%{change}",
    "practice.next_harder": "🔥 Nice! Next questions: {difficulty}",
    "practice.next_easier": "🙂 Let's build up again. Next questions: {difficulty}",
    "practice.unreadable": "🤔 I couldn't read that as an answer.\nWrite a number or an expression, for example:",

    # Solution steps (formulas are added by the code on the next line)
    "step.add": "Add {n} to both sides:",
    "step.subtract": "Subtract {n} from both sides:",
    "step.divide": "Divide both sides by {n}:",
    "step.expand": "Expand the brackets:",
    "step.x_one_side": "Bring the x terms to one side:",
    "step.factor": "Factor it:",
    "step.zero_factors": "Each factor can be zero, so:",
    "step.substitute": "Put the number in place of x:",
    "step.calculate": "Calculate:",
    "step.terms": "Work out each term:",
    "step.add_up": "Add them up:",
    "step.power_rule": "Use the power rule:",
    "step.so": "So:",
    "step.each_term": "Differentiate each term. A number on its own becomes 0:",

    # Pop-up notices (shown briefly at the top of the chat)
    "toast.saved": "✅ Saved",
    "toast.cleared": "✅ Cleared {count} saved messages",
    "toast.nothing_to_clear": "Nothing to clear",
    "toast.coming_soon": "⏳ Coming soon",
    "toast.not_your_menu": "This menu belongs to someone else. Send /start to get your own.",
    "toast.question_over": "This question is already finished.",

    # Telegram's "/" command menu
    "command.start": "Open the main menu",
    "command.help": "Help and all commands",
}
