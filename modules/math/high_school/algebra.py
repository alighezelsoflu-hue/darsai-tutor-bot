import random

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
    a = random.randint(2, 8)
    b = random.randint(1, 9)
    x = random.randint(2, 10)
    c = a * (x + b)
    return {
        "question": f"Solve: {a}(x + {b}) = {c}",
        "answer": str(x),
        "topic": "algebra",
        "level": "high_school",
        "explanation": f"Divide by {a}: x + {b} = {x + b}. Then subtract {b}: x = {x}."
    }
