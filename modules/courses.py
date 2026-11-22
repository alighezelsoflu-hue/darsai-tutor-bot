"""Every course the bot has or will have. To add a course, add it here (plus its i18n text, see below).

Each course has:
- id: used in button routes ("c:<id>…") and in darsai_course_notify. Never change one.
- emoji and names: the name in every interface language (the course grid, the hub, the first lines).
- kind: SUBJECT (a school subject, follows the student's grade), PATH (a course with its own tracks, not
  tied to school grades) or EXAM (exam preparation: Konkur).
- live: False shows "🔜" and the course's coming-soon screen with 🔔 Notify me. Its text is the i18n
  string "soon.<id>".
- hub: the buttons of the course's hub, in order (live courses). "next" is ▶️ Practice: <suggested
  topic> on its own row; the others go two per row (see ui/courses.py).
- tutor and rules: who the AI tutor is for the course and how it teaches (tutor_prompt). The courses that
  aren't live have drafts, not used yet.

The screens are in ui/courses.py.
"""

from dataclasses import dataclass
from typing import Dict, Tuple

from config import BOT_NAME
from modules.common import PLAIN_TEXT_RULE

SUBJECT = "subject"
PATH = "path"
EXAM = "exam"

# Kept for the Math tutor, word for word from before courses existed.
_MATH_RULES = (
    "Do not just give the final answer. Teach step by step.",
    "Start with the intuition in simple language.",
    "Show formulas and substitutions clearly.",
    "Diagnose likely mistakes kindly.",
    "Give one small similar example or ask one check question at the end.",
    "Keep explanations focused and appropriate for the student's level.",
    "If a deterministic result is provided, do not change it; explain it.",
)
PERSIAN_FORMULA_RULE = (
    "Write every formula on its own line, never inside a Persian sentence, because right-to-left text reorders it."
)


@dataclass(frozen=True)
class Course:
    id: str
    emoji: str
    names: Dict[str, str]
    kind: str
    live: bool
    hub: Tuple[str, ...]
    tutor: str
    rules: Tuple[str, ...]

    def name(self, lang: str) -> str:
        return self.names.get(lang) or self.names["en"]

    def label(self, lang: str) -> str:
        """The course's button: "📐 Math", or "⚛️ Physics 🔜" when it isn't live."""
        return f"{self.emoji} {self.name(lang)}" + ("" if self.live else " 🔜")


# The order here is the order of the course buttons: school subjects first, then the path courses. EXAM courses
# get a row of their own after the others.
COURSES: Dict[str, Course] = {course.id: course for course in (
    Course(
        id="math", emoji="📐", names={"en": "Math", "fa": "ریاضی"}, kind=SUBJECT, live=True,
        hub=("next", "learn", "prac", "konkur", "tutor", "solve", "plot"),
        tutor="a specialized math tutor for students",
        rules=_MATH_RULES,
    ),
    Course(
        id="physics", emoji="⚛️", names={"en": "Physics", "fa": "فیزیک"}, kind=SUBJECT, live=False, hub=(),
        tutor="a specialized physics tutor for students",
        rules=(
            "Do not just give the final answer. Teach step by step.",
            "Start with the physical idea in simple language, with an everyday example.",
            "Write the formula, say what each symbol means, then substitute with units.",
            "Check that the units of the result make sense.",
            "Diagnose likely mistakes kindly.",
            "Give one small similar example or ask one check question at the end.",
        ),
    ),
    Course(
        id="chemistry", emoji="🧪", names={"en": "Chemistry", "fa": "شیمی"}, kind=SUBJECT, live=False, hub=(),
        tutor="a specialized chemistry tutor for students",
        rules=(
            "Do not just give the final answer. Teach step by step.",
            "Start with what happens to the atoms and molecules, in simple language.",
            "Balance every reaction and check it.",
            "Show molar mass and unit calculations clearly.",
            "Diagnose likely mistakes kindly.",
            "Give one small similar example or ask one check question at the end.",
        ),
    ),
    Course(
        id="biology", emoji="🧬", names={"en": "Biology", "fa": "زیست‌شناسی"}, kind=SUBJECT, live=False, hub=(),
        tutor="a specialized biology tutor for students",
        rules=(
            "Do not just give the final answer. Teach step by step.",
            "Start with the big picture in simple language, then the details.",
            "Explain each scientific term the first time you use it.",
            "Describe processes as numbered steps in order.",
            "Connect structure to function.",
            "Diagnose common misconceptions kindly.",
            "Give one small similar example or ask one check question at the end.",
        ),
    ),
    Course(
        id="ai", emoji="🤖", names={"en": "AI course", "fa": "هوش مصنوعی"}, kind=PATH, live=False, hub=(),
        tutor="a friendly teacher of an introductory course about artificial intelligence",
        rules=(
            "Explain ideas with everyday examples before any technical words.",
            "Match the student's age: simple and playful for young students, more precise for university students.",
            "Be honest about what AI can and can't do, including its mistakes and biases.",
            "Encourage using AI to learn, not to copy answers for homework or exams.",
            "Ask one check question at the end.",
        ),
    ),
    Course(
        id="astronomy", emoji="🔭", names={"en": "Astronomy", "fa": "نجوم"}, kind=PATH, live=False, hub=(),
        tutor="an astronomy teacher for curious students",
        rules=(
            "Explain with what the student can see in the sky themselves.",
            "Give sizes and distances with comparisons the student can picture.",
            "Separate what scientists know from what is still unknown.",
            "Ask one check question at the end.",
        ),
    ),
    Course(
        id="konkur", emoji="🎯", names={"en": "Konkur", "fa": "کنکور"}, kind=EXAM, live=False, hub=(),
        tutor="a Konkur (Iranian university entrance exam) coach",
        rules=(
            "Solve multiple-choice questions step by step, then say which choice is right.",
            "Show a quick way to rule out wrong choices when there is one.",
            "Remind the student that wrong answers cost marks, so skipping is better than guessing blindly.",
            "Point out which chapter the question comes from.",
        ),
    ),
)}

# The course grid (home and setup): everything but the exam courses, which get a row of their own.
GRID = tuple(course_id for course_id, course in COURSES.items() if course.kind != EXAM)
EXAMS = tuple(course_id for course_id, course in COURSES.items() if course.kind == EXAM)
COMING_SOON = tuple(course_id for course_id, course in COURSES.items() if not course.live)


def tutor_prompt(course_id: str, level: str, topic: str, language: str) -> str:
    """The AI tutor's system prompt for a course."""
    course = COURSES[course_id]
    rules = list(course.rules) + [PLAIN_TEXT_RULE]
    if language.lower().startswith(("persian", "farsi")):
        rules.append(PERSIAN_FORMULA_RULE)
    return (
        f"You are {BOT_NAME}, {course.tutor}.\n"
        f"Student level: {level.replace('_', ' ').title()}.\n"
        f"Topic: {topic}.\n"
        f"Respond in {language}.\n\n"
        "Teaching rules:\n"
        + "\n".join(f"{number}. {rule}" for number, rule in enumerate(rules, 1))
    )
