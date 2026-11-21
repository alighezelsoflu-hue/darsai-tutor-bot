import random

from ..shared import poly_text

TOPICS = {"precalculus": "Functions, trigonometry, sequences, and preparation for calculus"}


def lesson(topic: str = "precalculus") -> str:
    return (
        "Pre-College Precalculus\n\n"
        "Precalculus connects algebra, functions, graphs, and trigonometry.\n"
        "It prepares you for limits, derivatives, and integrals.\n\n"
        "Core idea: understand how a function behaves, not only how to calculate values."
    )


def substitution_text(terms, x: int) -> str:
    """Write f(x) with the number in place of x: (2, 2), (-3, 1), (1, 0) at -2 -> '2(-2)^2 - 3(-2) + 1'."""
    parts = []
    for coefficient, power in terms:
        if coefficient == 0:
            continue
        magnitude = abs(coefficient)
        if power == 0:
            body = str(magnitude)
        else:
            body = f"({x})" if power == 1 else f"({x})^{power}"
            if magnitude != 1:
                body = f"{magnitude}{body}"
        if not parts:
            parts.append(f"-{body}" if coefficient < 0 else body)
        else:
            parts.append(f"- {body}" if coefficient < 0 else f"+ {body}")
    return " ".join(parts)


def practice(difficulty: str = "medium") -> dict:
    """easy: f(x) = ax + b at a small positive x. medium: negatives too. hard: f(x) = ax^2 + bx + c."""
    if difficulty == "hard":
        terms = [
            (random.choice([-3, -2, -1, 1, 2, 3]), 2),
            (random.randint(-5, 5), 1),
            (random.randint(-9, 9), 0),
        ]
        x = random.choice([-3, -2, -1, 1, 2, 3])
    elif difficulty == "easy":
        terms = [(random.randint(1, 5), 1), (random.randint(1, 9), 0)]
        x = random.randint(1, 5)
    else:
        terms = [(random.randint(1, 5), 1), (random.randint(-5, 5), 0)]
        x = random.randint(-4, 4)
    values = [coefficient * x ** power for coefficient, power in terms if coefficient]
    y = sum(values)
    point = f"f({x})"
    steps = [["substitute", {}, f"{point} = {substitution_text(terms, x)}"]]
    if difficulty == "hard" and len(values) > 1:
        steps.append(["terms", {}, f"{point} = {poly_text(*((v, 0) for v in values))}"])
        steps.append(["add_up", {}, f"{point} = {y}"])
    else:
        steps.append(["calculate", {}, f"{point} = {y}"])
    return {
        "level": "pre_college",
        "topic": "precalculus",
        "difficulty": difficulty if difficulty in ("easy", "hard") else "medium",
        "prompt": "evaluate",
        "formula": [f"f(x) = {poly_text(*terms)}", f"{point} = ?"],
        "answer": str(y),
        "steps": steps,
    }
