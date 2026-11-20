import random

from ..shared import poly_text

TOPICS = {"quadratics": "Quadratic equations and parabolas"}


def lesson(topic: str = "quadratics") -> str:
    return (
        "Quadratic equations\n\n"
        "A quadratic equation has x² as the highest power. Standard form is ax² + bx + c = 0.\n\n"
        "Main methods:\n"
        "1. Factoring\n"
        "2. Completing the square\n"
        "3. Quadratic formula\n\n"
        "Example:\n"
        "x² - 5x + 6 = 0\n"
        "Factor: (x - 2)(x - 3) = 0\n"
        "So x = 2 or x = 3."
    )


def factor_text(root: int) -> str:
    """The factor that is zero at this root: 2 -> (x - 2), -3 -> (x + 3), 0 -> x."""
    if root == 0:
        return "x"
    return f"({poly_text((1, 1), (-root, 0))})"


def practice(difficulty: str = "medium") -> dict:
    r1 = random.randint(-5, 5)
    r2 = random.randint(-5, 5)
    while r2 == r1:
        r2 = random.randint(-5, 5)
    r1, r2 = sorted([r1, r2])
    b = -(r1 + r2)
    c = r1 * r2
    return {
        "question": f"Solve: {poly_text((1, 2), (b, 1), (c, 0))} = 0",
        "answer": f"{r1},{r2}",
        "topic": "quadratics",
        "level": "high_school",
        "explanation": f"The equation factors as {factor_text(r1)}{factor_text(r2)} = 0, so x = {r1} or x = {r2}.",
    }
