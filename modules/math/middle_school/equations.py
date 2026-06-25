import random

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


def practice(difficulty: str = "easy") -> dict:
    a = random.randint(2, 9)
    x = random.randint(2, 12)
    b = random.randint(-10, 10)
    c = a * x + b
    sign = "+" if b >= 0 else "-"
    question = f"Solve: {a}x {sign} {abs(b)} = {c}"
    return {"question": question, "answer": str(x), "topic": "linear_equations", "level": "middle_school", "explanation": f"Subtract {b} from both sides, then divide by {a}. x = {x}."}
