import random

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


def practice(difficulty: str = "medium") -> dict:
    r1 = random.randint(-5, 5)
    r2 = random.randint(-5, 5)
    while r2 == r1:
        r2 = random.randint(-5, 5)
    b = -(r1 + r2)
    c = r1 * r2
    b_text = f"+ {b}" if b >= 0 else f"- {abs(b)}"
    c_text = f"+ {c}" if c >= 0 else f"- {abs(c)}"
    return {
        "question": f"Solve: x^2 {b_text}x {c_text} = 0",
        "answer": ",".join(str(v) for v in sorted([r1, r2])),
        "topic": "quadratics",
        "level": "high_school",
        "explanation": f"The equation factors as (x - {r1})(x - {r2}) = 0, so x = {r1} or x = {r2}."
    }
