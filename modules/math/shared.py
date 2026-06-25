import ast
import math
import operator
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from config import DATABASE_URL

try:
    import psycopg
except Exception:
    psycopg = None

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

LANGUAGES = {
    "en": "English", "fa": "Persian/Farsi", "de": "German", "it": "Italian",
    "fr": "French", "es": "Spanish", "ar": "Arabic",
    "farsi": "Persian/Farsi", "persian": "Persian/Farsi",
    "german": "German", "italian": "Italian", "french": "French", "spanish": "Spanish", "arabic": "Arabic",
}

PROFILE_FALLBACK: Dict[Tuple[int, int], Dict[str, str]] = {}
PROGRESS_FALLBACK: Dict[Tuple[int, int, str, str], Dict[str, int]] = {}


def db_available() -> bool:
    return bool(DATABASE_URL and psycopg)


def get_conn():
    if not db_available():
        return None
    return psycopg.connect(DATABASE_URL)


def init_math_db() -> None:
    if not db_available():
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
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
        conn.commit()


def normalize_level(text: str, default: str = "high_school") -> str:
    key = (text or "").strip().lower().replace("-", "_").replace(" ", "_")
    return LEVELS.get(key, default)


def extract_language(text: str, default: str = "English") -> Tuple[str, str]:
    parts = text.strip().split()
    if parts and parts[0].lower() in LANGUAGES:
        return " ".join(parts[1:]).strip(), LANGUAGES[parts[0].lower()]
    return text.strip(), default


def get_user_level(chat_id: int, user_id: int) -> str:
    if db_available():
        init_math_db()
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT level FROM darsai_user_profile WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
                row = cur.fetchone()
                if row:
                    return row[0]
    return PROFILE_FALLBACK.get((chat_id, user_id), {}).get("level", "high_school")


def set_user_level(chat_id: int, user_id: int, level: str) -> str:
    level = normalize_level(level)
    if db_available():
        init_math_db()
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO darsai_user_profile (chat_id, user_id, level)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (chat_id, user_id)
                    DO UPDATE SET level=EXCLUDED.level, updated_at=NOW();
                """, (chat_id, user_id, level))
            conn.commit()
    PROFILE_FALLBACK.setdefault((chat_id, user_id), {})["level"] = level
    return level


def record_progress(chat_id: int, user_id: int, level: str, topic: str, correct: bool) -> None:
    level = normalize_level(level)
    topic = normalize_topic(topic)
    correct_delta = 1 if correct else 0
    wrong_delta = 0 if correct else 1
    if db_available():
        init_math_db()
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO darsai_math_progress (chat_id, user_id, level, topic, correct_count, wrong_count)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (chat_id, user_id, level, topic)
                    DO UPDATE SET
                        correct_count = darsai_math_progress.correct_count + EXCLUDED.correct_count,
                        wrong_count = darsai_math_progress.wrong_count + EXCLUDED.wrong_count,
                        updated_at = NOW();
                """, (chat_id, user_id, level, topic, correct_delta, wrong_delta))
            conn.commit()
        return
    key = (chat_id, user_id, level, topic)
    PROGRESS_FALLBACK.setdefault(key, {"correct": 0, "wrong": 0})
    PROGRESS_FALLBACK[key]["correct"] += correct_delta
    PROGRESS_FALLBACK[key]["wrong"] += wrong_delta


def progress_report(chat_id: int, user_id: int) -> str:
    rows = []
    if db_available():
        init_math_db()
        with get_conn() as conn:
            with conn.cursor() as cur:
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


def normalize_topic(text: str) -> str:
    return (text or "general").strip().lower().replace(" ", "_").replace("-", "_")


# ------------------------------------------------------------
# Safe math expression tools
# ------------------------------------------------------------

SAFE_FUNCTIONS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
    "exp": math.exp, "abs": abs, "floor": math.floor, "ceil": math.ceil,
}
SAFE_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
_ALLOWED_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}
_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def normalize_expression(expr: str) -> str:
    expr = expr.strip()
    expr = expr.replace("^", "**")
    expr = re.sub(r"(?<=\d)(?=[a-zA-Z(])", "*", expr)
    expr = re.sub(r"(?<=\))(?=\d|[a-zA-Z])", "*", expr)
    return expr


def safe_eval(expr: str, x: Optional[float] = None) -> float:
    expr = normalize_expression(expr)
    tree = ast.parse(expr, mode="eval")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError("Only numbers are allowed.")
        if isinstance(node, ast.Name):
            if node.id == "x" and x is not None:
                return float(x)
            if node.id in SAFE_CONSTANTS:
                return SAFE_CONSTANTS[node.id]
            raise ValueError(f"Unknown name: {node.id}")
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            left, right = _eval(node.left), _eval(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10:
                raise ValueError("Power too large.")
            return _ALLOWED_BINOPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
            return _ALLOWED_UNARY[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in SAFE_FUNCTIONS:
            args = [_eval(arg) for arg in node.args]
            if len(args) > 2:
                raise ValueError("Too many function arguments.")
            return float(SAFE_FUNCTIONS[node.func.id](*args))
        raise ValueError("Unsupported expression.")

    result = _eval(tree)
    if not math.isfinite(result):
        raise ValueError("Result is not finite.")
    return result


def solve_equation(equation: str) -> Dict[str, object]:
    if "=" not in equation:
        return {"type": "arithmetic", "result": safe_eval(equation)}
    lhs, rhs = equation.split("=", 1)
    diff_expr = f"({lhs})-({rhs})"
    # Sample f(0), f(1), f(2) and infer linear/quadratic.
    f0 = safe_eval(diff_expr, x=0)
    f1 = safe_eval(diff_expr, x=1)
    f2 = safe_eval(diff_expr, x=2)
    a = (f2 - 2 * f1 + f0) / 2
    b = f1 - f0 - a
    c = f0
    if abs(a) < 1e-10:
        if abs(b) < 1e-10:
            raise ValueError("Equation has no unique solution." if abs(c) > 1e-10 else "Equation is true for many x values.")
        x = -c / b
        return {"type": "linear", "solutions": [x], "a": b, "b": c}
    disc = b * b - 4 * a * c
    if disc < -1e-10:
        return {"type": "quadratic", "solutions": [], "a": a, "b": b, "c": c, "discriminant": disc}
    if abs(disc) < 1e-10:
        return {"type": "quadratic", "solutions": [-b / (2 * a)], "a": a, "b": b, "c": c, "discriminant": 0.0}
    root = math.sqrt(disc)
    return {"type": "quadratic", "solutions": [(-b - root) / (2 * a), (-b + root) / (2 * a)], "a": a, "b": b, "c": c, "discriminant": disc}


def nice(value: float, digits: int = 6) -> str:
    if abs(value) < 1e-12:
        value = 0.0
    if abs(value - round(value)) < 1e-12:
        return str(int(round(value)))
    return f"{value:.{digits}g}"
