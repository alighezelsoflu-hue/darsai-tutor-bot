import random

from ..shared import number_step, poly_text

TOPICS = {"linear_equations": "One-step and two-step linear equations"}


def lesson(topic: str = "linear_equations") -> str:
    return (
        "Linear equations — Middle School\n\n"
        "A linear equation has a variable like x. Your goal is to get x alone.\n\n"
        "Example:\n"
        "2x + 5 = 17\n"
        "Subtract 5 from both sides: 2x = 12\n"
        "Divide by 2: x = 6\n\n"
        "Rule: whatever you do to one side, do to the other side."
    )


def practice(difficulty: str = "medium") -> dict:
    """easy: one step (x + b = c or ax = c). medium: ax + b = c. hard: x on both sides."""
    steps = []
    if difficulty == "easy":
        x = random.randint(1, 12)
        if random.random() < 0.5:
            b = random.choice([n for n in range(-9, 10) if n])
            equation = f"{poly_text((1, 1), (b, 0))} = {x + b}"
            steps.append(number_step(b, f"x = {x}"))
        else:
            a = random.randint(2, 9)
            equation = f"{a}x = {a * x}"
            steps.append(["divide", {"n": a}, f"x = {x}"])
    elif difficulty == "hard":
        a = random.randint(3, 9)
        c = random.randint(1, a - 1)
        x = random.randint(-9, 9)
        b = random.randint(-10, 10)
        d = (a - c) * x + b
        k = a - c
        equation = f"{poly_text((a, 1), (b, 0))} = {poly_text((c, 1), (d, 0))}"
        steps.append(["x_one_side", {}, f"{poly_text((k, 1), (b, 0))} = {d}"])
        if b:
            steps.append(number_step(b, f"{poly_text((k, 1))} = {d - b}"))
        if k != 1:
            steps.append(["divide", {"n": k}, f"x = {x}"])
    else:
        a = random.randint(2, 9)
        x = random.randint(2, 12)
        b = random.randint(-10, 10)
        c = a * x + b
        equation = f"{poly_text((a, 1), (b, 0))} = {c}"
        if b:
            steps.append(number_step(b, f"{a}x = {c - b}"))
        steps.append(["divide", {"n": a}, f"x = {x}"])
    return {
        "level": "middle_school",
        "topic": "linear_equations",
        "difficulty": difficulty if difficulty in ("easy", "hard") else "medium",
        "prompt": "solve",
        "formula": [equation],
        "answer": str(x),
        "steps": steps,
    }
