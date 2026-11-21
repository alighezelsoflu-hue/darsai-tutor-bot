import random

from ..shared import number_step, poly_text

TOPICS = {"algebra": "Algebra expressions and equations"}


def lesson(topic: str = "algebra") -> str:
    return (
        "High School Algebra\n\n"
        "Algebra uses symbols like x to represent unknown numbers.\n"
        "Key skills: simplifying expressions, solving equations, factoring, and using functions.\n\n"
        "Example:\n"
        "3(x + 2) = 21\n"
        "Distribute: 3x + 6 = 21\n"
        "Subtract 6: 3x = 15\n"
        "Divide by 3: x = 5"
    )


def practice(difficulty: str = "medium") -> dict:
    """easy: a(x + b) = c with small positive numbers. medium: negatives too. hard: a(x + b) = cx + d."""
    steps = []
    if difficulty == "hard":
        a = random.randint(2, 7)
        c = random.randint(1, a - 1)
        b = random.choice([n for n in range(-9, 10) if n])
        x = random.randint(-9, 9)
        d = a * (x + b) - c * x
        k = a - c
        equation = f"{a}({poly_text((1, 1), (b, 0))}) = {poly_text((c, 1), (d, 0))}"
        steps.append(["expand", {}, f"{poly_text((a, 1), (a * b, 0))} = {poly_text((c, 1), (d, 0))}"])
        steps.append(["x_one_side", {}, f"{poly_text((k, 1), (a * b, 0))} = {d}"])
        steps.append(number_step(a * b, f"{poly_text((k, 1))} = {d - a * b}"))
        if k != 1:
            steps.append(["divide", {"n": k}, f"x = {x}"])
    else:
        if difficulty == "easy":
            a, b, x = random.randint(2, 5), random.randint(1, 5), random.randint(1, 6)
        else:
            a = random.randint(2, 9)
            b = random.choice([n for n in range(-9, 10) if n])
            x = random.randint(-10, 10)
        c = a * (x + b)
        equation = f"{a}({poly_text((1, 1), (b, 0))}) = {c}"
        steps.append(["divide", {"n": a}, f"{poly_text((1, 1), (b, 0))} = {x + b}"])
        steps.append(number_step(b, f"x = {x}"))
    return {
        "level": "high_school",
        "topic": "algebra",
        "difficulty": difficulty if difficulty in ("easy", "hard") else "medium",
        "prompt": "solve",
        "formula": [equation],
        "answer": str(x),
        "steps": steps,
    }
