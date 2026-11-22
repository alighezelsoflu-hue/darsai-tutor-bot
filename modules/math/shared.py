import ast
import json
import math
import operator
import re
import threading
from typing import Callable, Dict, List, Optional, Tuple

from modules.db import connection, db_configured
from modules.student import get_student, set_level

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

DIFFICULTIES = ("easy", "medium", "hard")

# In-memory fallbacks, used only when DATABASE_URL is not set (local testing).
MASTERY_FALLBACK: Dict[Tuple[int, str, str], Dict[str, float]] = {}
ACTIVE_QUESTION_FALLBACK: Dict[Tuple[int, int], Dict[str, object]] = {}
_FALLBACK_LOCK = threading.Lock()


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
            CREATE TABLE IF NOT EXISTS darsai_mastery (
                user_id BIGINT NOT NULL,
                level TEXT NOT NULL,
                topic TEXT NOT NULL,
                mastery DOUBLE PRECISION NOT NULL DEFAULT 0,
                correct_count INTEGER NOT NULL DEFAULT 0,
                wrong_count INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY(user_id, level, topic)
            );
        """)
        _copy_old_progress(cur)
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


def normalize_difficulty(text: str, default: str = "") -> str:
    key = (text or "").strip().lower()
    return next((d for d in DIFFICULTIES if key in (d, d[0])), default)


def get_user_level(chat_id: int, user_id: int) -> str:
    """The student's level. It is the same in every chat."""
    level = get_student(user_id)["level"]
    if level:
        return normalize_level(level)
    if db_configured():
        # Levels used to be saved per chat in darsai_user_profile. Keep reading them for older students.
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT level FROM darsai_user_profile WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
            row = cur.fetchone()
        if row:
            return normalize_level(row[0])
    return DEFAULT_LEVEL


def set_user_level(chat_id: int, user_id: int, level: str) -> str:
    """Save the student's level for every chat. chat_id is kept for callers' convenience."""
    level = normalize_level(level)
    set_level(user_id, level)
    return level


# Mastery is how well a student knows a topic, from 0 to 1. It is the same in every chat.
# A correct answer moves it a step towards the ceiling of the question's difficulty, so easy questions
# alone can never reach 100%. A missed question takes away a share of it.
MASTERY_CEILING = {"easy": 0.6, "medium": 0.85, "hard": 1.0}
MASTERY_GAIN = {"first_try": 0.3, "second_try": 0.15}
MASTERY_LOSS = {"easy": 0.25, "medium": 0.2, "hard": 0.15}
OUTCOMES = ("first_try", "second_try", "missed")


def next_mastery(mastery: float, difficulty: str, outcome: str) -> float:
    if outcome in MASTERY_GAIN:
        mastery += MASTERY_GAIN[outcome] * max(0.0, MASTERY_CEILING[difficulty] - mastery)
    else:
        mastery -= MASTERY_LOSS[difficulty] * mastery
    return min(1.0, max(0.0, mastery))


def recommended_difficulty(mastery: float) -> str:
    if mastery < 0.4:
        return "easy"
    if mastery < 0.7:
        return "medium"
    return "hard"


def _copy_old_progress(cur) -> None:
    """Copy counts from darsai_math_progress (per chat, before mastery existed) into darsai_mastery once.

    Mastery is estimated as if every old answer was a medium question. Students who already have
    mastery rows are left alone, so running this at every startup changes nothing after the first time.
    """
    cur.execute("SELECT to_regclass('darsai_math_progress') IS NOT NULL")
    if not cur.fetchone()[0]:
        return
    cur.execute("""
        INSERT INTO darsai_mastery (user_id, level, topic, mastery, correct_count, wrong_count)
        SELECT user_id, level, topic,
               CASE WHEN SUM(correct_count + wrong_count) = 0 THEN 0
                    ELSE 0.85 * SUM(correct_count)::float / SUM(correct_count + wrong_count)
                         * (1 - power(0.7::float, LEAST(SUM(correct_count + wrong_count), 50)::float))
               END,
               SUM(correct_count), SUM(wrong_count)
        FROM darsai_math_progress
        GROUP BY user_id, level, topic
        ON CONFLICT (user_id, level, topic) DO NOTHING;
    """)


def record_answer(user_id: int, level: str, topic: str, difficulty: str, outcome: str) -> Tuple[float, float]:
    """Update the student's mastery of a topic after a practice question. Returns (before, after)."""
    level = normalize_level(level)
    topic = normalize_topic(topic)
    difficulty = normalize_difficulty(difficulty, default="medium")
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown outcome: {outcome}")
    correct = 0 if outcome == "missed" else 1
    if db_configured():
        key = (user_id, level, topic)
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO darsai_mastery (user_id, level, topic) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                key,
            )
            # Lock the row, so two answers at the same moment can't both start from the same value.
            cur.execute(
                "SELECT mastery FROM darsai_mastery WHERE user_id=%s AND level=%s AND topic=%s FOR UPDATE", key
            )
            before = float(cur.fetchone()[0])
            after = next_mastery(before, difficulty, outcome)
            cur.execute("""
                UPDATE darsai_mastery
                SET mastery=%s, correct_count=correct_count + %s, wrong_count=wrong_count + %s, updated_at=NOW()
                WHERE user_id=%s AND level=%s AND topic=%s
            """, (after, correct, 1 - correct) + key)
        return before, after
    with _FALLBACK_LOCK:
        entry = MASTERY_FALLBACK.setdefault((user_id, level, topic), {"mastery": 0.0, "correct": 0, "wrong": 0})
        before = entry["mastery"]
        entry["mastery"] = next_mastery(before, difficulty, outcome)
        entry["correct"] += correct
        entry["wrong"] += 1 - correct
        # Most recently practised first, like the database query.
        MASTERY_FALLBACK[(user_id, level, topic)] = MASTERY_FALLBACK.pop((user_id, level, topic))
        return before, entry["mastery"]


def get_mastery(user_id: int) -> Dict[Tuple[str, str], Dict[str, float]]:
    """{(level, topic): {"mastery", "correct", "wrong"}} for every topic the student has practised.

    The most recently practised topic comes first.
    """
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT level, topic, mastery, correct_count, wrong_count
                FROM darsai_mastery WHERE user_id=%s ORDER BY updated_at DESC
            """, (user_id,))
            rows = cur.fetchall()
        return {(level, topic): {"mastery": float(m), "correct": c, "wrong": w} for level, topic, m, c, w in rows}
    with _FALLBACK_LOCK:
        entries = [(key, dict(value)) for key, value in MASTERY_FALLBACK.items() if key[0] == user_id]
    return {(level, topic): value for (_, level, topic), value in reversed(entries)}


def progress_report(user_id: int) -> str:
    """Plain-English progress summary for the old /progress command."""
    rows = list(get_mastery(user_id).items())[:20]
    if not rows:
        return "No math progress yet. Try /practice high_school algebra"
    lines = ["Your DarsAI math progress 📈", ""]
    for (level, topic), entry in rows:
        lines.append(
            f"- {LEVEL_LABELS.get(level, level)} / {topic}: {entry['correct']} correct, "
            f"{entry['wrong']} wrong, mastery {int(round(100 * entry['mastery']))}%"
        )
    return "\n".join(lines)


def save_active_question(chat_id: int, user_id: int, question: Dict[str, object]) -> None:
    """Make this the practice question the student is working on in this chat, replacing any other.

    To change the question the student already has (e.g. count a try), use update_active_question.
    """
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO darsai_active_question (chat_id, user_id, question)
                VALUES (%s, %s, %s::jsonb)
                ON CONFLICT (chat_id, user_id)
                DO UPDATE SET question=EXCLUDED.question, created_at=NOW();
            """, (chat_id, user_id, json.dumps(question)))
        return
    # A JSON round trip, like the JSONB column: the caller's dict and the stored one never share lists.
    with _FALLBACK_LOCK:
        ACTIVE_QUESTION_FALLBACK[(chat_id, user_id)] = json.loads(json.dumps(question))


def update_active_question(chat_id: int, user_id: int, question: Dict[str, object]) -> bool:
    """Save changes to the active question, but only while it is still the same question (same id).

    Returns False when the question was finished or replaced in the meantime. So a question that
    Show solution or another answer just finished can never come back and be counted twice.
    """
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE darsai_active_question SET question=%s::jsonb
                WHERE chat_id=%s AND user_id=%s AND question->>'id'=%s
            """, (json.dumps(question), chat_id, user_id, str(question["id"])))
            return cur.rowcount > 0
    with _FALLBACK_LOCK:
        stored = ACTIVE_QUESTION_FALLBACK.get((chat_id, user_id))
        if stored is None or stored.get("id") != question["id"]:
            return False
        ACTIVE_QUESTION_FALLBACK[(chat_id, user_id)] = json.loads(json.dumps(question))
        return True


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
    with _FALLBACK_LOCK:
        question = ACTIVE_QUESTION_FALLBACK.get((chat_id, user_id))
        return json.loads(json.dumps(question)) if question else None


def clear_active_question(chat_id: int, user_id: int, question_id: Optional[str] = None) -> bool:
    """Forget the active question. With question_id, only if it is still that question.

    Returns True if a question was removed, so when two answers arrive at once only one of them counts.
    """
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            if question_id is None:
                cur.execute("DELETE FROM darsai_active_question WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
            else:
                cur.execute(
                    "DELETE FROM darsai_active_question WHERE chat_id=%s AND user_id=%s AND question->>'id'=%s",
                    (chat_id, user_id, question_id),
                )
            return cur.rowcount > 0
    with _FALLBACK_LOCK:
        question = ACTIVE_QUESTION_FALLBACK.get((chat_id, user_id))
        if question is None or (question_id is not None and question.get("id") != question_id):
            return False
        del ACTIVE_QUESTION_FALLBACK[(chat_id, user_id)]
        return True


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

# Separators between several answers: "2, 3", "x = 2 or x = 3", "2 یا 3", "2، 3" (Persian comma).
_ANSWER_SPLIT = re.compile(r"\s*(?:,|;|،|؛|&|\bor\b|\band\b|\bیا\b|\bو\b)\s*", re.IGNORECASE)
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


def answer_count(text: str) -> int:
    """How many separate answers the text contains ("2, 3" has two)."""
    return len(_answer_parts(text))


def readable_answer(text: str) -> bool:
    """True when every part of the text is a number or an expression we can evaluate.

    Practice uses this to tell an answer ("5", "x = 2 or 3") from other text ("I don't know").
    """
    parts = _answer_parts(text)
    if not parts:
        return False
    try:
        for part in parts:
            _answer_values(part)
    except ValueError:
        return False
    return True


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


def number_step(number: int, formula: str) -> list:
    """The solution step that takes a number off one side: subtract it, or add its opposite.

    Step numbers are always positive, because a minus sign inside a Persian sentence gets reordered.
    """
    return ["subtract", {"n": number}, formula] if number > 0 else ["add", {"n": -number}, formula]


def nice(value: float, digits: int = 6) -> str:
    if abs(value) < 1e-12:
        value = 0.0
    if abs(value - round(value)) < 1e-12:
        return str(int(round(value)))
    return f"{value:.{digits}g}"
