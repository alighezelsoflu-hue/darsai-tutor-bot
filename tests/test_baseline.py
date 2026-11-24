"""Memory and uptime (modules/metrics.py), the /stats server line, and a tiny run of scripts/load_test.py so the
load test keeps working."""

import asyncio
import contextlib
import io
import unittest

from modules import metrics, stats
from scripts import load_test
from tests.test_ui import TelegramMocks


class MetricsTests(unittest.TestCase):
    def test_memory_and_uptime(self):
        current, peak = metrics.memory_mb()
        self.assertGreater(peak, 1)
        if current is not None:  # Linux
            self.assertGreater(current, 1)
        self.assertGreaterEqual(metrics.uptime_seconds(), 0)
        self.assertRegex(metrics.describe(), r"^memory (\d+ MB \(peak \d+ MB\)|peak \d+ MB) of 512 MB, up \d+ (min|h \d\d min)$")

    def test_stats_ends_with_the_server_line(self):
        numbers = stats.collect_stats(stats.activity.utc_today(), admins=())
        numbers["server"] = "memory 140 MB (peak 160 MB) of 512 MB, up 3 h 05 min"
        self.assertTrue(stats.format_stats(numbers).endswith("\n\n🖥 This server: memory 140 MB (peak 160 MB) of 512 MB, up 3 h 05 min."))


class LoadTestTests(TelegramMocks):
    def test_a_tiny_run_has_no_errors(self):
        args = load_test.parse_args(["--students", "4", "--ramp", "0", "--think", "0", "--telegram-ms", "0", "--ai-seconds", "0"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            recorder = asyncio.run(load_test.main_async(args))
        self.assertEqual(recorder.errors, 0, output.getvalue())
        self.assertEqual(sum(len(times) for times in recorder.times.values()), 4 * 20)
        self.assertIn("4 students, 80 updates", output.getvalue())
        self.assertIn("tutor: question (AI)", output.getvalue())
        self.assertIn("Speed limit: 0 updates refused (20 per 10 s)", output.getvalue())
