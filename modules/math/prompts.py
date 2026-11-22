from modules.courses import tutor_prompt


def math_tutor_prompt(level: str = "high_school", topic: str = "math", language: str = "English") -> str:
    """The Math tutor's system prompt. Its rules are in modules/courses.py with the other courses."""
    return tutor_prompt("math", level, topic, language)
