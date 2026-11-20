import random

from ..shared import poly_text

TOPICS = {"calculus": "Limits, derivatives, and integrals"}


def lesson(topic: str = "calculus") -> str:
    return (
        "University Calculus\n\n"
        "Calculus studies change and accumulation.\n"
        "Derivative = instantaneous rate of change.\n"
        "Integral = accumulated area or total change.\n\n"
        "Example: if f(x)=x², then f'(x)=2x."
    )


def practice(difficulty: str = "medium") -> dict:
    n = random.randint(2, 5)
    a = random.randint(2, 8)
    derivative = poly_text((a * n, n - 1))
    return {
        "question": f"Find the derivative of f(x) = {poly_text((a, n))}.",
        "answer": derivative,
        "topic": "calculus",
        "level": "university",
        "explanation": f"Use the power rule: d/dx [a x^n] = a*n*x^(n-1). Here {a}*{n} = {a * n}, so f'(x) = {derivative}.",
    }
