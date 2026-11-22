import random
from fractions import Fraction

from ..shared import poly_text

TOPICS = {"quadratics": "Quadratic equations and parabolas"}


def lesson() -> dict:
    """Intro blocks and a worked example, as i18n keys and formula lines (see practice() for the step format)."""
    return {
        "level": "high_school",
        "topic": "quadratics",
        "intro": [
            ["lesson.quadratics.idea", {}, "ax^2 + bx + c = 0"],
            ["lesson.quadratics.factor", {}, ""],
            ["lesson.quadratics.formula", {}, "x = (-b ± √(b^2 - 4ac)) / 2a"],
        ],
        "example": {
            "prompt": "solve",
            "formula": ["x^2 - 5x + 6 = 0"],
            "steps": [
                ["factor", {}, "(x - 2)(x - 3) = 0"],
                ["zero_factors", {}, "x = 2, x = 3"],
            ],
        },
    }


def factor_text(root: int) -> str:
    """The factor that is zero at this root: 2 -> (x - 2), -3 -> (x + 3), 0 -> x."""
    if root == 0:
        return "x"
    return f"({poly_text((1, 1), (-root, 0))})"


def practice(difficulty: str = "medium") -> dict:
    """easy: two positive whole roots. medium: roots from -5 to 5. hard: one root is a fraction, like 1/2."""
    if difficulty == "hard":
        p = random.choice([2, 3])
        q = random.choice([n for n in range(-7, 8) if n % p])
        r = random.randint(-5, 5)
        equation = poly_text((p, 2), (-p * r - q, 1), (q * r, 0))
        factored = f"{factor_text(r)}({poly_text((p, 1), (-q, 0))})"
        roots = sorted([Fraction(q, p), Fraction(r)])
    else:
        low, high = (1, 6) if difficulty == "easy" else (-5, 5)
        r1, r2 = sorted(random.sample(range(low, high + 1), 2))
        equation = poly_text((1, 2), (-(r1 + r2), 1), (r1 * r2, 0))
        factored = f"{factor_text(r1)}{factor_text(r2)}"
        roots = [Fraction(r1), Fraction(r2)]
    return {
        "level": "high_school",
        "topic": "quadratics",
        "difficulty": difficulty if difficulty in ("easy", "hard") else "medium",
        "prompt": "solve",
        "formula": [f"{equation} = 0"],
        "answer": ",".join(str(root) for root in roots),
        "steps": [
            ["factor", {}, f"{factored} = 0"],
            ["zero_factors", {}, ", ".join(f"x = {root}" for root in roots)],
        ],
    }
