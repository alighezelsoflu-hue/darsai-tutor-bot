import random

from ..shared import poly_text

TOPICS = {"calculus": "Limits, derivatives, and integrals"}

POWER_RULE = "(x^n)' = n·x^(n-1)"


def lesson() -> dict:
    """Intro blocks and a worked example, as i18n keys and formula lines (see practice() for the step format)."""
    return {
        "level": "university",
        "topic": "calculus",
        "intro": [
            ["lesson.calculus.idea", {}, ""],
            ["step.power_rule", {}, POWER_RULE],
        ],
        "example": {
            "prompt": "derivative",
            "formula": ["f(x) = 3x^2 + 5x - 4", "f'(x) = ?"],
            "steps": [
                ["each_term", {}, "f'(x) = 6x + 5"],
            ],
        },
    }


def practice(difficulty: str = "medium") -> dict:
    """easy: ax^n. medium: ax^n + bx + c. hard: a cubic with every term."""
    if difficulty == "easy":
        a, n = random.randint(1, 6), random.randint(2, 4)
        terms = [(a, n)]
    elif difficulty == "hard":
        terms = [
            (random.choice([-5, -4, -3, -2, -1, 1, 2, 3, 4, 5]), 3),
            (random.randint(-6, 6), 2),
            (random.randint(-9, 9), 1),
            (random.randint(-9, 9), 0),
        ]
    else:
        terms = [
            (random.randint(1, 6), random.randint(2, 4)),
            (random.choice([n for n in range(-9, 10) if n]), 1),
            (random.randint(-9, 9), 0),
        ]
    # Power rule on every term. The constant term (power 0) drops out.
    derivative = poly_text(*((c * p, p - 1) for c, p in terms if p > 0))
    steps = [["power_rule", {}, POWER_RULE]]
    if difficulty == "easy" and a != 1:
        lowered = "x" if n == 2 else f"x^{n - 1}"
        steps.append(["so", {}, f"f'(x) = {a}·{n}{lowered} = {derivative}"])
    elif difficulty == "easy":
        steps.append(["so", {}, f"f'(x) = {derivative}"])
    else:
        steps.append(["each_term", {}, f"f'(x) = {derivative}"])
    return {
        "level": "university",
        "topic": "calculus",
        "difficulty": difficulty if difficulty in ("easy", "hard") else "medium",
        "prompt": "derivative",
        "formula": [f"f(x) = {poly_text(*terms)}", "f'(x) = ?"],
        "answer": derivative,
        "steps": steps,
    }
