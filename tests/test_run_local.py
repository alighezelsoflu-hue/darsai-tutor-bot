import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import run_local


class LoadEnvFileTests(unittest.TestCase):
    def test_parses_lines_and_keeps_shell_values(self):
        content = (
            "# comment\n"
            "\n"
            "DARSAI_T_PLAIN=abc\n"
            "export DARSAI_T_EXPORTED=1\n"
            'DARSAI_T_QUOTED="a b=c"\n'
            "DARSAI_T_SHELL=from-file\n"
            "not a setting\n"
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"DARSAI_T_SHELL": "from-shell"}):
            path = Path(tmp) / ".env.local"
            path.write_text(content, encoding="utf-8")
            run_local.load_env_file(path)
            self.assertEqual(os.environ["DARSAI_T_PLAIN"], "abc")
            self.assertEqual(os.environ["DARSAI_T_EXPORTED"], "1")
            self.assertEqual(os.environ["DARSAI_T_QUOTED"], "a b=c")
            self.assertEqual(os.environ["DARSAI_T_SHELL"], "from-shell")

    def test_missing_file_is_ignored(self):
        run_local.load_env_file(Path("/nonexistent/.env.local"))


class PrepareEnvironmentTests(unittest.TestCase):
    def test_uses_only_the_local_token_and_database(self):
        env = {
            "LOCAL_TELEGRAM_BOT_TOKEN": "111:TEST",
            "TELEGRAM_BOT_TOKEN": "999:PRODUCTION",
            "DATABASE_URL": "postgresql://production",
        }
        with patch.dict(os.environ, env), patch.object(run_local, "ENV_FILE", Path("/nonexistent/.env.local")):
            os.environ.pop("LOCAL_DATABASE_URL", None)
            run_local.prepare_environment()
            self.assertEqual(os.environ["TELEGRAM_BOT_TOKEN"], "111:TEST")
            self.assertEqual(os.environ["DATABASE_URL"], "")

    def test_exits_without_a_local_token(self):
        with patch.dict(os.environ, {}), patch.object(run_local, "ENV_FILE", Path("/nonexistent/.env.local")):
            os.environ.pop("LOCAL_TELEGRAM_BOT_TOKEN", None)
            with self.assertRaises(SystemExit):
                run_local.prepare_environment()


class ProductionGuardTests(unittest.TestCase):
    def test_refuses_a_bot_with_a_webhook(self):
        bot = SimpleNamespace(get_webhook_info=AsyncMock(return_value=SimpleNamespace(url="https://prod.example/hook")))
        with self.assertRaises(run_local.ProductionBotError):
            asyncio.run(run_local.ensure_not_production(bot))

    def test_allows_a_bot_without_a_webhook(self):
        bot = SimpleNamespace(get_webhook_info=AsyncMock(return_value=SimpleNamespace(url="")))
        asyncio.run(run_local.ensure_not_production(bot))
