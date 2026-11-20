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


def practice(difficulty: str = "medium") -> dict:
    a = random.randint(1, 5)
    b = random.randint(-5, 5)
    x = random.randint(-4, 4)
    y = a * x + b
    substitution = f"{a}({x})" if a != 1 else f"({x})"
    if b > 0:
        substitution += f" + {b}"
    elif b < 0:
        substitution += f" - {-b}"
    return {
        "question": f"For f(x) = {poly_text((a, 1), (b, 0))}, find f({x}).",
        "answer": str(y),
        "topic": "precalculus",
        "level": "pre_college",
        "explanation": f"Substitute x = {x}: f({x}) = {substitution} = {y}.",
    }
