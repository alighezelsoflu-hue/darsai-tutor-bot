import json
import random
import re
import unittest
from fractions import Fraction

from modules.i18n import STRINGS
from modules.math import shared
from modules.math.high_school import algebra, quadratics
from modules.math.middle_school import equations
from modules.math.pre_college import precalculus
from modules.math.shared import (
    DIFFICULTIES,
    Expression,
    SolveError,
    UnsupportedEquation,
    answers_match,
    get_mastery,
    next_mastery,
    normalize_difficulty,
    poly_text,
    progress_report,
    readable_answer,
    recommended_difficulty,
    record_answer,
    safe_eval,
    solve_equation,
)
from modules.math.topics import MATH_MEMORY_TOPICS, TOPIC_LEVEL, TOPIC_MODULES
from modules.math.university import calculus


class ExpressionTests(unittest.TestCase):
    def test_student_notation(self):
        cases = [
            ("2x + 1", 3, 7),
            ("x^2", 3, 9),
            ("x²", 3, 9),
            ("2(x + 1)", 2, 6),
            ("(x + 1)(x - 1)", 3, 8),
            ("x(x + 1)", 2, 6),
            ("2pi", None, 2 * 3.141592653589793),
            ("3×4 ÷ 2", None, 6),
            ("۲x", 3, 6),
            ("log10(100)", None, 2),
            ("log(8, 2)", None, 3),
            ("1e-3", None, 0.001),
            ("2e", None, 2 * 2.718281828459045),
            ("2^x", 20, 2 ** 20),
        ]
        for text, x, expected in cases:
            with self.subTest(text=text):
                self.assertAlmostEqual(safe_eval(text, x=x), expected)

    def test_rejects_unsafe_or_invalid_input(self):
        for text in ["__import__('os')", "x.real", "(-8)^(1/3)", "1/0", "sqrt(-1)", "2 3", "sin x", "1" * 300, ""]:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    safe_eval(text, x=1)

    def test_uses_x(self):
        self.assertTrue(Expression("2x + 1").uses_x)
        self.assertFalse(Expression("exp(2)").uses_x)


class SolverTests(unittest.TestCase):
    def solutions(self, equation):
        return [round(v, 6) for v in solve_equation(equation)["solutions"]]

    def test_linear_and_quadratic(self):
        self.assertEqual(self.solutions("2x + 5 = 17"), [6])
        self.assertEqual(self.solutions("x^2 - 5x + 6 = 0"), [2, 3])
        self.assertEqual(self.solutions("x^2 - 4 = 0"), [-2, 2])
        self.assertEqual(self.solutions("x^2 - 2x + 1 = 0"), [1])
        self.assertEqual(self.solutions("x^2 + 1 = 0"), [])
        self.assertEqual(self.solutions("x^2 = 2"), [-1.414214, 1.414214])
        self.assertEqual(self.solutions("3(x + 2) = 21"), [5])
        self.assertEqual(self.solutions("0.1x + 0.2 = 0.3"), [1])

    def test_arithmetic(self):
        self.assertEqual(solve_equation("3*4+2"), {"type": "arithmetic", "result": 14.0})

    def test_refuses_equations_it_cannot_solve(self):
        for equation in ["x^3 = 8", "2^x = 8", "sin(x) = 0", "1/x = 2", "sqrt(x) = 3"]:
            with self.subTest(equation=equation):
                with self.assertRaises(UnsupportedEquation):
                    solve_equation(equation)

    def test_degenerate_and_malformed(self):
        for equation in ["x = x", "x + 1 = x", "2x + 1", "1 = 1", "x = ", "x = 1 = 2"]:
            with self.subTest(equation=equation):
                with self.assertRaises(ValueError):
                    solve_equation(equation)

    def test_error_codes_for_translated_messages(self):
        cases = {"x = x": "every_x", "x + 1 = x": "no_solution", "2x + 1": "needs_equals",
                 "1 = 1": "no_x", "x = ": "empty_side", "x = 1 = 2": "two_equals"}
        for equation, code in cases.items():
            with self.subTest(equation=equation):
                with self.assertRaises(SolveError) as caught:
                    solve_equation(equation)
                self.assertEqual(caught.exception.code, code)


class AnswerMatchTests(unittest.TestCase):
    def test_equivalent_answers(self):
        cases = [
            ("6", "6"),
            ("6", " x = 6 "),
            ("6", "12/2"),
            ("-3,-2", "-2, -3"),
            ("-3,-2", "x = -3 or x = -2"),
            ("-3,-2", "x1=-2; x2=-3"),
            ("-3,-2", "-۳ یا -۲"),
            ("-3,-2", "-۳، -۲"),
            ("-5,5/2", "x = 2.5 or x = -5"),
            ("-3,-2", "x = -3\nx = -2"),
            ("-3,-2", "\u200e-3, -2"),
            ("12x", "12x^1"),
            ("12x", "12*x"),
            ("12x", "f'(x) = 12x"),
            ("20x^3", "20x³"),
        ]
        for expected, given in cases:
            with self.subTest(expected=expected, given=given):
                self.assertTrue(answers_match(expected, given))

    def test_wrong_answers(self):
        cases = [("6", "5"), ("6", "x"), ("-3,-2", "-3"), ("-3,-2", "-3, 2"), ("12x", "12x^2"), ("12x", "6x"), ("6", "")]
        for expected, given in cases:
            with self.subTest(expected=expected, given=given):
                self.assertFalse(answers_match(expected, given))

    def test_readable_answers(self):
        for text in ("5", "x = -2 or 3", "-۳، -۲", "12x^3", "1/2"):
            with self.subTest(text=text):
                self.assertTrue(readable_answer(text))
        for text in ("", "I don't know", "نمی‌دونم", "hello", "2 +", "x = "):
            with self.subTest(text=text):
                self.assertFalse(readable_answer(text))


class FormattingTests(unittest.TestCase):
    def test_poly_text(self):
        self.assertEqual(poly_text((1, 2), (-5, 1), (6, 0)), "x^2 - 5x + 6")
        self.assertEqual(poly_text((1, 2), (0, 1), (-4, 0)), "x^2 - 4")
        self.assertEqual(poly_text((-1, 1), (0, 0)), "-x")
        self.assertEqual(poly_text((12, 1)), "12x")
        self.assertEqual(poly_text((0, 1), (0, 0)), "0")


class PracticeGeneratorTests(unittest.TestCase):
    BAD_FORMATTING = re.compile(r"\+ -|- -|[+-] 0x|[+-] 0(?!\d)|x\^1(?!\d)|(?<!\d)1x|x - -|\+ 0 =")

    def run_generator(self, module, check):
        rng_state = random.getstate()
        try:
            random.seed(1234)
            for difficulty in DIFFICULTIES:
                for _ in range(200):
                    q = module.practice(difficulty)
                    self.assertEqual(q["difficulty"], difficulty)
                    self.assertEqual(json.loads(json.dumps(q)), q, "must survive the JSONB column unchanged")
                    self.assertIn(f"prompt.{q['prompt']}", STRINGS["en"])
                    for text in q["formula"] + [q["answer"]] + [step[2] for step in q["steps"]]:
                        self.assertIsNone(self.BAD_FORMATTING.search(text), text)
                    for key, params, _ in q["steps"]:
                        self.assertIn(f"step.{key}", STRINGS["en"])
                        # Numbers inside sentences are positive: a minus sign gets reordered in Persian.
                        self.assertTrue(all(isinstance(v, int) and v > 0 for v in params.values()), q)
                    self.assertTrue(answers_match(q["answer"], q["answer"]))
                    self.assertTrue(answers_match(q["answer"], q["steps"][-1][2]), "the last step shows the answer")
                    check(q)
        finally:
            random.setstate(rng_state)

    def assert_solve_matches(self, q):
        solutions = ",".join(str(v) for v in solve_equation(q["formula"][0])["solutions"])
        self.assertTrue(answers_match(q["answer"], solutions), q)

    def test_middle_school_equations(self):
        def check(q):
            self.assert_solve_matches(q)
            if q["difficulty"] == "easy":
                self.assertEqual(len(q["steps"]), 1, q)
            if q["difficulty"] == "hard":
                self.assertIn("x", q["formula"][0].split("=")[1], q)
        self.run_generator(equations, check)

    def test_high_school_algebra(self):
        self.run_generator(algebra, self.assert_solve_matches)

    def test_quadratics(self):
        def check(q):
            self.assert_solve_matches(q)
            roots = [Fraction(root) for root in q["answer"].split(",")]
            if q["difficulty"] == "easy":
                self.assertTrue(all(root > 0 for root in roots), q)
            if q["difficulty"] == "hard":
                self.assertTrue(any(root.denominator > 1 for root in roots), q)
        self.run_generator(quadratics, check)

    def test_precalculus(self):
        def check(q):
            function = re.fullmatch(r"f\(x\) = (.+)", q["formula"][0]).group(1)
            x = re.fullmatch(r"f\((-?\d+)\) = \?", q["formula"][1]).group(1)
            self.assertAlmostEqual(safe_eval(function, x=float(x)), float(q["answer"]))
            self.assertEqual("x^2" in function, q["difficulty"] == "hard", q)
        self.run_generator(precalculus, check)

    def test_calculus(self):
        def check(q):
            f = Expression(re.fullmatch(r"f\(x\) = (.+)", q["formula"][0]).group(1))
            derivative = Expression(q["answer"])
            for x in (0.5, 1.5, 2.0):
                h = 1e-5
                numeric = (f(x + h) - f(x - h)) / (2 * h)
                self.assertAlmostEqual(derivative(x), numeric, places=3)
        self.run_generator(calculus, check)

    def test_unknown_difficulty_is_medium(self):
        self.assertEqual(algebra.practice("wizard")["difficulty"], "medium")
        self.assertEqual(normalize_difficulty("H"), "hard")
        self.assertEqual(normalize_difficulty("wizard"), "")

    def test_topic_names_are_unique_and_have_memory(self):
        self.assertEqual(len(TOPIC_LEVEL), len(TOPIC_MODULES))
        self.assertEqual(set(MATH_MEMORY_TOPICS), {"math"} | set(TOPIC_LEVEL))
        for topic in TOPIC_LEVEL:
            self.assertIn(f"topic.{topic}", STRINGS["en"])


class LessonTests(unittest.TestCase):
    def test_lessons_use_known_strings_and_a_correct_example(self):
        for (level, topic), module in TOPIC_MODULES.items():
            with self.subTest(topic=topic):
                lesson = module.lesson()
                self.assertEqual((lesson["level"], lesson["topic"]), (level, topic))
                self.assertEqual(json.loads(json.dumps(lesson)), lesson)
                for key, params, _ in lesson["intro"]:
                    self.assertIn(key, STRINGS["en"])
                example = lesson["example"]
                self.assertIn(f"prompt.{example['prompt']}", STRINGS["en"])
                for key, params, _ in example["steps"]:
                    self.assertIn(f"step.{key}", STRINGS["en"])
                    self.assertTrue(all(isinstance(v, int) and v > 0 for v in params.values()))
                if example["prompt"] == "solve":
                    solutions = ",".join(str(v) for v in solve_equation(example["formula"][0])["solutions"])
                    answer_step = next(f for k, _, f in reversed(example["steps"]) if k != "check")
                    self.assertTrue(answers_match(answer_step, solutions), lesson)


class MasteryTests(unittest.TestCase):
    def setUp(self):
        shared.MASTERY_FALLBACK.clear()

    def test_correct_answers_never_lower_mastery(self):
        for difficulty in DIFFICULTIES:
            for start in (0.0, 0.3, 0.7, 0.95):
                for outcome in ("first_try", "second_try"):
                    self.assertGreaterEqual(next_mastery(start, difficulty, outcome), start)
                self.assertLess(next_mastery(start or 0.5, difficulty, "missed"), start or 0.5)

    def test_easy_questions_alone_cannot_reach_full_mastery(self):
        mastery = 0.0
        for _ in range(100):
            mastery = next_mastery(mastery, "easy", "first_try")
        self.assertAlmostEqual(mastery, shared.MASTERY_CEILING["easy"], places=3)
        self.assertGreater(next_mastery(mastery, "hard", "first_try"), mastery)

    def test_a_first_try_counts_more_than_a_second_try(self):
        self.assertGreater(next_mastery(0.2, "medium", "first_try"), next_mastery(0.2, "medium", "second_try"))

    def test_recommended_difficulty_climbs_with_correct_answers(self):
        mastery, seen = 0.0, []
        for _ in range(15):
            difficulty = recommended_difficulty(mastery)
            seen.append(difficulty)
            mastery = next_mastery(mastery, difficulty, "first_try")
        self.assertEqual(seen[0], "easy")
        self.assertEqual(seen[-1], "hard")
        self.assertEqual(seen, sorted(seen, key=DIFFICULTIES.index), "never goes back down while answers are right")

    def test_recorded_per_student_not_per_chat(self):
        before, after = record_answer(42, "high_school", "algebra", "easy", "first_try")
        self.assertEqual(before, 0.0)
        self.assertAlmostEqual(after, 0.18)
        record_answer(42, "high_school", "quadratics", "medium", "missed")
        record_answer(7, "high_school", "algebra", "hard", "first_try")
        mastery = get_mastery(42)
        self.assertEqual(list(mastery), [("high_school", "quadratics"), ("high_school", "algebra")])
        self.assertEqual(mastery[("high_school", "algebra")], {"mastery": after, "correct": 1, "wrong": 0})
        self.assertEqual(mastery[("high_school", "quadratics")]["wrong"], 1)
        self.assertIn("algebra: 1 correct, 0 wrong, mastery 18%", progress_report(42))
        self.assertIn("No math progress yet", progress_report(99))


if __name__ == "__main__":
    unittest.main()
