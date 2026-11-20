import ast
import json
import math
import operator
import re
from typing import Callable, Dict, List, Optional, Tuple

from modules.db import connection, db_configured

LEVELS = {
    "middle": "middle_school",
    "middle_school": "middle_school",
    "middleschool": "middle_school",
    "high": "high_school",
    "high_school": "high_school",
    "highschool": "high_school",
    "pre": "pre_college",
    "precollege": "pre_college",
    "pre_college": "pre_college",
    "college": "pre_college",
    "university": "university",
    "uni": "university",
}

LEVEL_LABELS = {
    "middle_school": "Middle School",
    "high_school": "High School",
    "pre_college": "Pre-College",
    "university": "University",
}

DEFAULT_LEVEL = "high_school"

# In-memory fallbacks, used only when DATABASE_URL is not set (local testing).
PROFILE_FALLBACK: Dict[Tuple[int, int], Dict[str, str]] = {}
PROGRESS_FALLBACK: Dict[Tuple[int, int, str, str], Dict[str, int]] = {}
ACTIVE_QUESTION_FALLBACK: Dict[Tuple[int, int], Dict[str, object]] = {}


# ------------------------------------------------------------
# Profiles, progress and active practice questions
# ------------------------------------------------------------
# All functions in this section are blocking. Call them with asyncio.to_thread.

def init_math_db() -> None:
    if not db_configured():
        return
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS darsai_user_profile (
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                level TEXT NOT NULL DEFAULT 'high_school',
                language TEXT NOT NULL DEFAULT 'en',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY(chat_id, user_id)
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS darsai_math_progress (
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                level TEXT NOT NULL,
                topic TEXT NOT NULL,
                correct_count INTEGER NOT NULL DEFAULT 0,
                wrong_count INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY(chat_id, user_id, level, topic)
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS darsai_active_question (
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                question JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY(chat_id, user_id)
            );
        """)


def normalize_level(text: str, default: str = DEFAULT_LEVEL) -> str:
    key = (text or "").strip().lower().replace("-", "_").replace(" ", "_")
    return LEVELS.get(key, default)


def normalize_topic(text: str) -> str:
    return (text or "general").strip().lower().replace(" ", "_").replace("-", "_")


def get_user_level(chat_id: int, user_id: int) -> str:
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT level FROM darsai_user_profile WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
            row = cur.fetchone()
        return row[0] if row else DEFAULT_LEVEL
    return PROFILE_FALLBACK.get((chat_id, user_id), {}).get("level", DEFAULT_LEVEL)


def set_user_level(chat_id: int, user_id: int, level: str) -> str:
    level = normalize_level(level)
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO darsai_user_profile (chat_id, user_id, level)
                VALUES (%s, %s, %s)
                ON CONFLICT (chat_id, user_id)
                DO UPDATE SET level=EXCLUDED.level, updated_at=NOW();
            """, (chat_id, user_id, level))
        return level
    PROFILE_FALLBACK.setdefault((chat_id, user_id), {})["level"] = level
    return level


def record_progress(chat_id: int, user_id: int, level: str, topic: str, correct: bool) -> None:
    level = normalize_level(level)
    topic = normalize_topic(topic)
    correct_delta = 1 if correct else 0
    wrong_delta = 0 if correct else 1
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO darsai_math_progress (chat_id, user_id, level, topic, correct_count, wrong_count)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (chat_id, user_id, level, topic)
                DO UPDATE SET
                    correct_count = darsai_math_progress.correct_count + EXCLUDED.correct_count,
                    wrong_count = darsai_math_progress.wrong_count + EXCLUDED.wrong_count,
                    updated_at = NOW();
            """, (chat_id, user_id, level, topic, correct_delta, wrong_delta))
        return
    key = (chat_id, user_id, level, topic)
    PROGRESS_FALLBACK.setdefault(key, {"correct": 0, "wrong": 0})
    PROGRESS_FALLBACK[key]["correct"] += correct_delta
    PROGRESS_FALLBACK[key]["wrong"] += wrong_delta


def progress_report(chat_id: int, user_id: int) -> str:
    rows = []
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT level, topic, correct_count, wrong_count
                FROM darsai_math_progress
                WHERE chat_id=%s AND user_id=%s
                ORDER BY updated_at DESC
                LIMIT 20;
            """, (chat_id, user_id))
            rows = cur.fetchall()
    else:
        for (c, u, level, topic), counts in PROGRESS_FALLBACK.items():
            if c == chat_id and u == user_id:
                rows.append((level, topic, counts["correct"], counts["wrong"]))

    if not rows:
        return "No math progress yet. Try /practice high_school algebra"

    lines = ["Your DarsAI math progress 📈", ""]
    for level, topic, correct, wrong in rows:
        total = correct + wrong
        mastery = int(round(100 * correct / total)) if total else 0
        lines.append(f"- {LEVEL_LABELS.get(level, level)} / {topic}: {correct} correct, {wrong} wrong, mastery ≈ {mastery}%")
    return "\n".join(lines)


def save_active_question(chat_id: int, user_id: int, question: Dict[str, object]) -> None:
    """Remember the practice question a student is working on in this chat."""
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO darsai_active_question (chat_id, user_id, question)
                VALUES (%s, %s, %s::jsonb)
                ON CONFLICT (chat_id, user_id)
                DO UPDATE SET question=EXCLUDED.question, created_at=NOW();
            """, (chat_id, user_id, json.dumps(question)))
        return
    ACTIVE_QUESTION_FALLBACK[(chat_id, user_id)] = dict(question)


def get_active_question(chat_id: int, user_id: int) -> Optional[Dict[str, object]]:
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT question FROM darsai_active_question WHERE chat_id=%s AND user_id=%s",
                (chat_id, user_id),
            )
            row = cur.fetchone()
        if not row:
            return None
        return json.loads(row[0]) if isinstance(row[0], str) else row[0]
    question = ACTIVE_QUESTION_FALLBACK.get((chat_id, user_id))
    return dict(question) if question else None


def clear_active_question(chat_id: int, user_id: int) -> None:
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM darsai_active_question WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
        return
    ACTIVE_QUESTION_FALLBACK.pop((chat_id, user_id), None)


# ------------------------------------------------------------
# Safe math expressions
# ------------------------------------------------------------

SAFE_FUNCTIONS: Dict[str, Callable[..., float]] = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
    "exp": math.exp, "abs": abs, "floor": math.floor, "ceil": math.ceil,
}
SAFE_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
_ALLOWED_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}
_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}

MAX_EXPRESSION_LENGTH = 200

_DIGIT_MAP = {ord(ch): str(i) for digits in ("۰۱۲۳۴۵۶۷۸۹", "٠١٢٣٤٥٦٧٨٩") for i, ch in enumerate(digits)}
_CHAR_MAP = {**_DIGIT_MAP, ord("×"): "*", ord("·"): "*", ord("÷"): "/", ord("−"): "-", ord("–"): "-", ord("٫"): "."}
_SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_SUPERSCRIPT_RUN = re.compile("[⁰¹²³⁴⁵⁶⁷⁸⁹]+")
_TOKEN_RE = re.compile(
    r"(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<op>\*\*|[-+*/%^(),])"
    r"|(?P<space>\s+)"
)


def _needs_multiplication(left: Tuple[str, str], right: Tuple[str, str]) -> bool:
    """True when two neighbouring tokens are an implied product, like 2x, 2(x+1), (x+1)(x-1), x(x+1)."""
    left_kind, left_text = left
    right_kind, right_text = right
    right_starts_factor = right_kind == "name" or right_text == "("
    if left_kind == "num":
        return right_starts_factor
    if left_text == ")":
        return right_starts_factor or right_kind == "num"
    if left_kind == "name" and left_text not in SAFE_FUNCTIONS:
        return right_starts_factor
    return False


def normalize_expression(expr: str) -> str:
    """Turn student notation (2x, x^2, x², 3×4, ۲x) into a Python expression string."""
    expr = (expr or "").translate(_CHAR_MAP)
    expr = _SUPERSCRIPT_RUN.sub(lambda m: "^" + m.group().translate(_SUPERSCRIPT_DIGITS), expr).strip()
    if not expr:
        raise ValueError("The expression is empty.")
    if len(expr) > MAX_EXPRESSION_LENGTH:
        raise ValueError(f"The expression is too long (max {MAX_EXPRESSION_LENGTH} characters).")

    tokens: List[Tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        match = _TOKEN_RE.match(expr, pos)
        if not match:
            raise ValueError(f"Unexpected character: {expr[pos]}")
        pos = match.end()
        if match.lastgroup != "space":
            tokens.append((match.lastgroup, match.group()))

    out: List[str] = []
    for index, token in enumerate(tokens):
        if index and _needs_multiplication(tokens[index - 1], token):
            out.append("*")
        out.append("**" if token[1] == "^" else token[1])
    return " ".join(out)


class Expression:
    """A parsed, safe math expression in x. Parse once, evaluate many times."""

    def __init__(self, text: str):
        self.text = text
        self.normalized = normalize_expression(text)
        try:
            self._tree = ast.parse(self.normalized, mode="eval")
        except SyntaxError:
            raise ValueError("Could not understand the expression. Check the brackets and operators.") from None
        self.uses_x = any(isinstance(node, ast.Name) and node.id == "x" for node in ast.walk(self._tree))

    def __call__(self, x: Optional[float] = None) -> float:
        try:
            result = self._eval(self._tree, x)
        except ZeroDivisionError:
            raise ValueError("Division by zero.") from None
        except OverflowError:
            raise ValueError("The number is too large.") from None
        except TypeError:
            raise ValueError("A function got the wrong number of arguments.") from None
        except RecursionError:
            raise ValueError("The expression is nested too deeply.") from None
        if not math.isfinite(result):
            raise ValueError("The result is not a finite number.")
        return result

    def _eval(self, node, x: Optional[float]) -> float:
        if isinstance(node, ast.Expression):
            return self._eval(node.body, x)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return float(node.value)
            raise ValueError("Only numbers are allowed.")
        if isinstance(node, ast.Name):
            if node.id == "x" and x is not None:
                return float(x)
            if node.id in SAFE_CONSTANTS:
                return SAFE_CONSTANTS[node.id]
            raise ValueError(f"Unknown name: {node.id}")
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            result = _ALLOWED_BINOPS[type(node.op)](self._eval(node.left, x), self._eval(node.right, x))
            if isinstance(result, complex):
                raise ValueError("The result is not a real number.")
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
            return _ALLOWED_UNARY[type(node.op)](self._eval(node.operand, x))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in SAFE_FUNCTIONS and not node.keywords:
            args = [self._eval(arg, x) for arg in node.args]
            if len(args) > 2:
                raise ValueError("Too many function arguments.")
            return float(SAFE_FUNCTIONS[node.func.id](*args))
        raise ValueError("Unsupported expression.")


def safe_eval(expr: str, x: Optional[float] = None) -> float:
    return Expression(expr)(x)


# ------------------------------------------------------------
# Equation solver (linear and quadratic in x)
# ------------------------------------------------------------

class UnsupportedEquation(ValueError):
    pass


UNSUPPORTED_EQUATION_MESSAGE = (
    "/solve handles linear and quadratic equations in x, like 2x + 5 = 17 or x^2 - 5x + 6 = 0.\n"
    "For other equations, ask the tutor: /math_tutor explain how to solve ..."
)
_SOLVE_SAMPLE_POINTS = (0.0, 1.0, 2.0)
# Extra points used to confirm the equation really is linear or quadratic.
_SOLVE_CHECK_POINTS = (-3.5, -1.25, 0.5, 3.0, 4.75)


def solve_equation(equation: str) -> Dict[str, object]:
    equation = (equation or "").strip()
    if equation.count("=") > 1:
        raise ValueError("Please write one equation with a single '=' sign.")

    if "=" not in equation:
        expression = Expression(equation)
        if expression.uses_x:
            raise ValueError("To solve for x, write an equation with '=', for example: /solve 2x + 5 = 17")
        return {"type": "arithmetic", "result": expression()}

    lhs, rhs = (side.strip() for side in equation.split("=", 1))
    if not lhs or not rhs:
        raise ValueError("Both sides of the equation need an expression.")
    f = Expression(f"({lhs})-({rhs})")
    if not f.uses_x:
        raise ValueError("There is no x to solve for. To calculate, leave out the '=' sign, for example: /solve 3*4+2")

    try:
        f0, f1, f2 = (f(point) for point in _SOLVE_SAMPLE_POINTS)
    except ValueError as error:
        raise UnsupportedEquation(UNSUPPORTED_EQUATION_MESSAGE) from error
    # The unique polynomial a*x^2 + b*x + c through the three sample points.
    a = (f2 - 2 * f1 + f0) / 2
    b = f1 - f0 - a
    c = f0

    for point in _SOLVE_CHECK_POINTS:
        try:
            actual = f(point)
        except ValueError as error:
            raise UnsupportedEquation(UNSUPPORTED_EQUATION_MESSAGE) from error
        predicted = (a * point + b) * point + c
        scale = max(1.0, abs(actual), abs(a * point * point) + abs(b * point) + abs(c))
        if abs(actual - predicted) > 1e-7 * scale:
            raise UnsupportedEquation(UNSUPPORTED_EQUATION_MESSAGE)

    # Clear floating-point noise relative to the largest coefficient.
    coefficient_scale = max(abs(a), abs(b), abs(c))
    a, b, c = (0.0 if abs(v) <= 1e-12 * coefficient_scale else v for v in (a, b, c))

    if a == 0:
        if b == 0:
            raise ValueError("This equation has no solution." if c != 0 else "This equation is true for every x.")
        return {"type": "linear", "solutions": [-c / b], "a": 0.0, "b": b, "c": c}

    disc = b * b - 4 * a * c
    disc_tolerance = 1e-12 * max(b * b, abs(4 * a * c))
    if disc < -disc_tolerance:
        return {"type": "quadratic", "solutions": [], "a": a, "b": b, "c": c, "discriminant": disc}
    if abs(disc) <= disc_tolerance:
        return {"type": "quadratic", "solutions": [-b / (2 * a)], "a": a, "b": b, "c": c, "discriminant": 0.0}
    # Numerically stable form of the quadratic formula.
    q = -0.5 * (b + math.copysign(math.sqrt(disc), b))
    return {"type": "quadratic", "solutions": sorted([q / a, c / q]), "a": a, "b": b, "c": c, "discriminant": disc}


# ------------------------------------------------------------
# Answer checking
# ------------------------------------------------------------

# Separators between several answers: "2, 3", "x = 2 or x = 3", "2 یا 3".
_ANSWER_SPLIT = re.compile(r"\s*(?:,|;|&|\bor\b|\band\b|\bیا\b|\bو\b)\s*", re.IGNORECASE)
_ANSWER_SAMPLE_POINTS = (-1.7, 0.6, 2.3)


def _answer_parts(text: str) -> List[str]:
    parts = []
    for part in _ANSWER_SPLIT.split((text or "").strip()):
        # Drop a leading "x =", "x1 =", "f'(x) =" and similar.
        part = part.rsplit("=", 1)[-1].strip()
        if part:
            parts.append(part)
    return parts


def _answer_values(text: str) -> Tuple[float, ...]:
    expression = Expression(text)
    return tuple(expression(point) for point in _ANSWER_SAMPLE_POINTS)


def _values_close(left: Tuple[float, ...], right: Tuple[float, ...]) -> bool:
    return all(abs(p - q) <= 1e-6 * max(1.0, abs(p), abs(q)) for p, q in zip(left, right))


def answers_match(expected: str, given: str) -> bool:
    """Compare answers by value, so "12x" matches "12x^1" and "-2, -3" matches "x = -3 or x = -2"."""
    expected_parts = _answer_parts(str(expected))
    given_parts = _answer_parts(given)
    if not expected_parts or len(expected_parts) != len(given_parts):
        return False
    try:
        expected_values = [_answer_values(part) for part in expected_parts]
        given_values = [_answer_values(part) for part in given_parts]
    except ValueError:
        def compact(parts: List[str]) -> List[str]:
            return sorted(part.replace(" ", "").lower() for part in parts)
        return compact(expected_parts) == compact(given_parts)

    remaining = list(given_values)
    for value in expected_values:
        index = next((i for i, candidate in enumerate(remaining) if _values_close(value, candidate)), None)
        if index is None:
            return False
        remaining.pop(index)
    return True


# ------------------------------------------------------------
# Formatting
# ------------------------------------------------------------

def poly_text(*terms: Tuple[int, int]) -> str:
    """Format integer polynomial terms [(coefficient, power), ...], e.g. (1, 2), (-5, 1), (6, 0) -> 'x^2 - 5x + 6'."""
    parts: List[str] = []
    for coefficient, power in terms:
        if coefficient == 0:
            continue
        magnitude = abs(coefficient)
        if power == 0:
            body = str(magnitude)
        else:
            variable = "x" if power == 1 else f"x^{power}"
            body = variable if magnitude == 1 else f"{magnitude}{variable}"
        if not parts:
            parts.append(f"-{body}" if coefficient < 0 else body)
        else:
            parts.append(f"- {body}" if coefficient < 0 else f"+ {body}")
    return " ".join(parts) if parts else "0"


def nice(value: float, digits: int = 6) -> str:
    if abs(value) < 1e-12:
        value = 0.0
    if abs(value - round(value)) < 1e-12:
        return str(int(round(value)))
    return f"{value:.{digits}g}"
