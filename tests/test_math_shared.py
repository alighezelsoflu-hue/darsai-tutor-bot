import random
import re
import unittest

from modules.math.high_school import algebra, quadratics
from modules.math.middle_school import equations
from modules.math.pre_college import precalculus
from modules.math.shared import (
    Expression,
    UnsupportedEquation,
    answers_match,
    poly_text,
    safe_eval,
    solve_equation,
)
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
            for _ in range(300):
                q = module.practice()
                for field in ("question", "answer", "explanation"):
                    self.assertIsNone(self.BAD_FORMATTING.search(q[field]), f"{field}: {q[field]}")
                self.assertTrue(answers_match(q["answer"], q["answer"]))
                check(q)
        finally:
            random.setstate(rng_state)

    def assert_solve_matches(self, q):
        equation = q["question"].split(":", 1)[1]
        solutions = ",".join(str(v) for v in solve_equation(equation)["solutions"])
        self.assertTrue(answers_match(q["answer"], solutions), q)

    def test_middle_school_equations(self):
        self.run_generator(equations, self.assert_solve_matches)

    def test_high_school_algebra(self):
        self.run_generator(algebra, self.assert_solve_matches)

    def test_quadratics(self):
        self.run_generator(quadratics, self.assert_solve_matches)

    def test_precalculus(self):
        def check(q):
            match = re.match(r"For f\(x\) = (.+), find f\((-?\d+)\)\.", q["question"])
            self.assertIsNotNone(match, q["question"])
            self.assertAlmostEqual(safe_eval(match.group(1), x=float(match.group(2))), float(q["answer"]))
        self.run_generator(precalculus, check)

    def test_calculus(self):
        def check(q):
            f = Expression(re.match(r"Find the derivative of f\(x\) = (.+)\.", q["question"]).group(1))
            derivative = Expression(q["answer"])
            for x in (0.5, 1.5, 2.0):
                h = 1e-5
                numeric = (f(x + h) - f(x - h)) / (2 * h)
                self.assertAlmostEqual(derivative(x), numeric, places=3)
        self.run_generator(calculus, check)


if __name__ == "__main__":
    unittest.main()
