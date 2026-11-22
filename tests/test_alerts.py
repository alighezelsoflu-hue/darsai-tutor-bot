"""Error alerts: scrubbing, grouping, the Telegram alerts to the admins, /alerttest and the Sentry option."""

import asyncio
import io
import logging
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch

import config
import main
from modules import admin, alerts
from tests.test_ui import TelegramMocks, run, text_update

ADMINS = frozenset({901, 902})
REAL_LOOKING_TOKEN = "7712345678:AAHk3xQ_example-secret-part-1234567890"


def error_record(message="Something failed", error=None, name="modules.example"):
    """A log record as logger.error / logger.exception make it."""
    exc_info = None
    if error is not None:
        try:
            raise error
        except Exception as raised:
            exc_info = (type(raised), raised, raised.__traceback__)
    return logging.LogRecord(name, logging.ERROR, __file__, 10, message, (), exc_info, func="caller")


class ScrubTests(unittest.TestCase):
    def test_secrets_are_replaced(self):
        with patch.multiple(config, GROQ_API_KEY="gsk_abcdefghijklmnop", DATABASE_URL="postgresql://bot:pw1234567@db.example/neondb",
                            SECRET_PATH="hook-9f8e7d6c5b", SENTRY_DSN="https://key123456@o1.ingest.sentry.io/2"):
            text = alerts.scrub(
                f"token {config.TOKEN}, url https://api.telegram.org/bot{REAL_LOOKING_TOKEN}/sendMessage, "
                f"secret {config.WEBHOOK_SECRET_TOKEN}, key gsk_abcdefghijklmnop, db postgresql://bot:pw1234567@db.example/neondb, "
                "other postgres://u:hunter2@host/x, path /hook-9f8e7d6c5b, dsn https://key123456@o1.ingest.sentry.io/2"
            )
        for secret in (config.TOKEN, REAL_LOOKING_TOKEN, config.WEBHOOK_SECRET_TOKEN, "gsk_abcdefghijklmnop",
                       "pw1234567", "hunter2", "hook-9f8e7d6c5b", "key123456"):
            self.assertNotIn(secret, text)
        self.assertIn("https://api.telegram.org/bot[redacted]/sendMessage", text)
        self.assertIn("postgres://u:[redacted]@host/x", text)

    def test_the_default_webhook_path_is_no_secret(self):
        self.assertEqual(alerts.scrub("POST /darsai-webhook"), "POST /darsai-webhook")

    def test_long_text_is_cut(self):
        self.assertEqual(len(alerts.shorten("x" * 1000)), alerts.MAX_TEXT_CHARS)
        self.assertEqual(alerts.shorten("a\n  b"), "a b")


class DescribeTests(unittest.TestCase):
    def test_an_exception_names_the_place_in_our_code(self):
        def raises():
            raise ValueError(f"bad value with {config.TOKEN}")

        try:
            raises()
        except ValueError as error:
            record = logging.LogRecord("darsai", logging.ERROR, __file__, 1, "Error while handling an update", (),
                                       (ValueError, error, error.__traceback__))
        kind, lines = alerts.describe(record)
        self.assertEqual(lines[0], "🚨 DarsAI error")
        self.assertEqual(lines[1], "ValueError: bad value with [redacted]")
        self.assertRegex(lines[2], r"^Where: tests/test_alerts\.py:\d+ in raises$")
        self.assertEqual(lines[3], "Log (darsai): Error while handling an update")
        self.assertTrue(lines[4].startswith("Time: ") and lines[4].endswith(" UTC"))
        self.assertEqual(kind[:3], ("darsai", "Error while handling an update", "ValueError"))

    def test_a_log_message_without_an_exception(self):
        record = logging.LogRecord("modules.ai", logging.ERROR, __file__, 7, "AI request failed: %s", ("HTTP 500",), None, func="log_ai_error")
        kind, lines = alerts.describe(record)
        self.assertEqual(lines[1], "Where: tests/test_alerts.py:7 in log_ai_error")
        self.assertEqual(lines[2], "Log (modules.ai): AI request failed: HTTP 500")
        # The same template with other values is the same kind.
        other = logging.LogRecord("modules.ai", logging.ERROR, __file__, 7, "AI request failed: %s", ("timeout",), None, func="log_ai_error")
        self.assertEqual(alerts.describe(other)[0], kind)


class ConsoleLogTests(unittest.TestCase):
    """No secret reaches the console (Render's log), whatever path it takes."""

    def capture(self, logger_name=""):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logger = logging.getLogger(logger_name)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        alerts.scrub_console_logs()
        return stream

    def test_main_scrubs_its_console_handler(self):
        handlers = [h for h in logging.getLogger().handlers if h is not alerts.admin_alerts]
        self.assertTrue(handlers)
        for handler in handlers:
            self.assertIsInstance(handler.formatter, alerts.ScrubbingFormatter)

    def test_an_exception_with_the_token_is_scrubbed_with_its_traceback(self):
        stream = self.capture()
        try:
            raise RuntimeError(f"failed with {config.TOKEN} and {REAL_LOOKING_TOKEN}")
        except RuntimeError:
            logging.getLogger("darsai").exception("Error while calling https://api.telegram.org/bot%s/getMe", config.TOKEN)
        output = stream.getvalue()
        self.assertIn("Traceback", output)
        self.assertIn("RuntimeError: failed with [redacted] and [redacted]", output)
        self.assertIn("https://api.telegram.org/bot[redacted]/getMe", output)
        for secret in (config.TOKEN, REAL_LOOKING_TOKEN):
            self.assertNotIn(secret, output)

    def test_uvicorn_access_lines_hide_a_custom_webhook_path(self):
        with patch.object(config, "SECRET_PATH", "hook-9f8e7d6c5b"):
            stream = self.capture("uvicorn.access")
            logging.getLogger("uvicorn.access").warning('1.2.3.4 - "POST /hook-9f8e7d6c5b HTTP/1.1" 200')
        self.assertIn('"POST /[redacted] HTTP/1.1"', stream.getvalue())

    def test_uncaught_exceptions_are_scrubbed(self):
        alerts.scrub_console_logs()
        try:
            raise RuntimeError(f"crash with {config.TOKEN}")
        except RuntimeError:
            exc_info = sys.exc_info()
        with patch.object(sys, "stderr", io.StringIO()) as stderr:
            sys.excepthook(*exc_info)
        self.assertIn("RuntimeError: crash with [redacted]", stderr.getvalue())
        self.assertNotIn(config.TOKEN, stderr.getvalue())

    def test_the_fake_token_looks_like_a_token(self):
        self.assertEqual(alerts.scrub(alerts.FAKE_TOKEN), "[redacted]")


class AdminAlertTests(unittest.TestCase):
    """The handler on its own, with a fake bot and a fake clock."""

    def setUp(self):
        self.handler = alerts.AdminAlerts()
        self.bot = SimpleNamespace(send_message=AsyncMock())
        self.now = 1_000_000.0
        for patcher in (
            patch.multiple(config, ADMIN_USER_IDS=ADMINS, ALERTS_TO_ADMINS=True, ALERT_REPEAT_MINUTES=30),
            patch.object(alerts.time, "time", side_effect=lambda: self.now),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def emit_all(self, *records):
        async def scenario():
            self.handler.start(self.bot)
            for record in records:
                self.handler.emit(record)
            await asyncio.sleep(0)
            await self.handler.drain()
        asyncio.run(scenario())

    def sent(self):
        return [(call.args[0], call.args[1]) for call in self.bot.send_message.call_args_list]

    def test_each_admin_gets_the_alert(self):
        self.emit_all(error_record(error=ValueError("boom")))
        sent = self.sent()
        self.assertEqual([admin_id for admin_id, _ in sent], [901, 902])
        self.assertIn("ValueError: boom", sent[0][1])
        self.assertEqual(sent[0][1], sent[1][1])

    def test_repeats_are_held_back_and_counted(self):
        self.emit_all(error_record(error=ValueError("boom")), error_record(error=ValueError("boom again")))
        self.assertEqual(len(self.sent()), 2, "one alert, to two admins")
        self.now += 29 * 60
        self.emit_all(error_record(error=ValueError("boom")))
        self.assertEqual(len(self.sent()), 2)
        self.now += 2 * 60
        self.emit_all(error_record(error=ValueError("boom")))
        self.assertEqual(len(self.sent()), 4)
        self.assertIn("+2 more like this since the last alert (at most one per 30 min).", self.sent()[-1][1])

    def test_other_kinds_go_out_up_to_the_cap(self):
        records = [error_record(f"Error number {n}") for n in range(alerts.MAX_ALERTS_PER_WINDOW + 2)]
        self.emit_all(*records)
        self.assertEqual(len(self.sent()), 2 * alerts.MAX_ALERTS_PER_WINDOW)
        self.now += 31 * 60
        self.emit_all(error_record("A new kind"))
        self.assertIn("+2 other errors were not sent (at most 10 alerts per 30 min).", self.sent()[-1][1])

    def test_off_without_admins_or_when_switched_off(self):
        with patch.object(config, "ALERTS_TO_ADMINS", False):
            self.emit_all(error_record())
        with patch.object(config, "ADMIN_USER_IDS", frozenset()):
            self.emit_all(error_record("other"))
        self.bot.send_message.assert_not_called()

    def test_nothing_before_start_and_nothing_from_this_module(self):
        self.handler.emit(error_record())  # not started: ignored, no error
        self.emit_all(error_record(name="modules.alerts"))
        self.bot.send_message.assert_not_called()

    def test_a_failed_alert_is_a_warning_and_never_another_alert(self):
        root = logging.getLogger()
        root.addHandler(self.handler)
        self.addCleanup(root.removeHandler, self.handler)

        async def fail(chat_id, text):
            logging.getLogger("telegram.ext").error("Network trouble while sending")  # logged while sending
            raise ConnectionError(f"no network ({config.TOKEN})")

        self.bot.send_message.side_effect = fail
        with self.assertLogs("modules.alerts", "WARNING") as logs:
            self.emit_all(error_record(error=ValueError("boom")))
        self.assertEqual(self.bot.send_message.call_count, 2, "only the two admins, no alert about the alert")
        self.assertIn("Could not send an error alert to admin 901: no network ([redacted])", logs.output[0])

    def test_errors_logged_in_worker_threads(self):
        logger = logging.getLogger("modules.worker_test")
        logger.addHandler(self.handler)
        self.addCleanup(logger.removeHandler, self.handler)

        async def scenario():
            self.handler.start(self.bot)
            await asyncio.to_thread(logger.error, "Database trouble")
            await asyncio.sleep(0)
            await self.handler.drain()

        asyncio.run(scenario())
        self.assertIn("Log (modules.worker_test): Database trouble", self.sent()[0][1])


class AlertTestCommandTests(TelegramMocks):
    ADMIN = 901

    def setUp(self):
        super().setUp()
        for patcher in (
            patch.object(admin, "ADMIN_USER_IDS", frozenset({self.ADMIN})),
            patch.multiple(config, ADMIN_USER_IDS=frozenset({self.ADMIN}), ALERTS_TO_ADMINS=True, ALERT_REPEAT_MINUTES=30),
            patch.object(main.telegram_app, "_initialized", True),
            # Commands are matched with the bot's username, which needs an initialized bot.
            patch.object(type(main.telegram_app.bot), "username", PropertyMock(return_value="darsai_test_bot")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        alerts.admin_alerts.reset()
        self.addCleanup(self.stop_alerts)

    def stop_alerts(self):
        alerts.admin_alerts._bot = None
        for name in ("", "uvicorn"):
            logging.getLogger(name).removeHandler(alerts.admin_alerts)
        alerts.admin_alerts.reset()

    def process(self, update, quiet=True):
        async def scenario():
            await alerts.start_alerts(main.telegram_app.bot)
            await main.telegram_app.process_update(update)
            await asyncio.sleep(0)
            await alerts.stop_alerts()
        if not quiet:
            asyncio.run(scenario())
            return
        # assertLogs replaces the root logger's handlers while it runs, so nothing is printed.
        with self.assertLogs(level="INFO"):
            asyncio.run(scenario())

    def alerts_sent(self):
        return [call for call in self.send_message.call_args_list if call.args[1].startswith("🚨")]

    def test_the_admin_gets_a_scrubbed_alert(self):
        console = io.StringIO()
        handler = logging.StreamHandler(console)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        alerts.scrub_console_logs()
        self.process(text_update("/alerttest", user_id=self.ADMIN), quiet=False)
        # The console (Render's log) shows the error, scrubbed, and never the real token.
        self.assertIn("AlertTestError: This is a test error from /alerttest (token check: [redacted])", console.getvalue())
        self.assertNotIn(alerts.FAKE_TOKEN, console.getvalue())
        self.assertNotIn(config.TOKEN, console.getvalue())
        self.assertIn("Raising a test error now", self.reply_text.call_args_list[0].args[0])
        (alert,) = self.alerts_sent()
        self.assertEqual(alert.args[0], self.ADMIN)
        text = alert.args[1]
        self.assertIn("AlertTestError: This is a test error from /alerttest (token check: [redacted])", text)
        self.assertIn("Where: modules/alerts.py:", text)
        self.assertIn("Log (darsai): Error while handling an update", text)
        self.assertNotIn(config.TOKEN, text)
        # The admin also sees what a student sees when something fails.
        self.assertIn("something went wrong", self.reply_text.call_args_list[-1].args[0])
        # A second one within the window is held back.
        self.process(text_update("/alerttest", user_id=self.ADMIN))
        self.assertEqual(len(self.alerts_sent()), 1)

    def test_anyone_else_gets_no_reply(self):
        with self.assertLogs("modules.admin", "INFO") as logs:
            run(alerts.alerttest_command, text_update("/alerttest", user_id=42))
            run(alerts.alerttest_command, text_update("/alerttest", user_id=self.ADMIN, chat_type="supergroup"))
        self.reply_text.assert_not_called()
        self.assertIn("Ignored /alerttest from user id 42 in a private chat", logs.output[0])


class SentryTests(unittest.TestCase):
    def test_off_without_a_dsn(self):
        with patch.object(config, "SENTRY_DSN", ""), patch("sentry_sdk.init") as init:
            self.assertFalse(alerts.init_sentry())
        init.assert_not_called()

    def test_options_keep_student_data_and_secrets_out(self):
        with patch.multiple(config, SENTRY_DSN="https://key@o1.ingest.sentry.io/2", SENTRY_ENVIRONMENT="staging"), \
                patch("sentry_sdk.init") as init:
            self.assertTrue(alerts.init_sentry())
        options = init.call_args.kwargs
        self.assertEqual(options["environment"], "staging")
        collection = options["data_collection"]
        self.assertIs(collection["user_info"], False)
        self.assertIs(collection["stack_frame_variables"], False)
        self.assertEqual(collection["http_bodies"], [])
        self.assertEqual(collection["http_headers"], {"request": {"mode": "off"}})
        self.assertIs(collection["gen_ai"]["inputs"], False)
        self.assertIs(options["include_local_variables"], False)
        self.assertEqual(options["max_request_body_size"], "never")
        self.assertIs(options["auto_enabling_integrations"], False)
        self.assertIs(options["before_send"], alerts.before_send)
        self.assertIs(options["before_breadcrumb"], alerts.before_breadcrumb)

    def test_a_failure_to_start_is_only_a_warning(self):
        with patch.object(config, "SENTRY_DSN", "not a dsn"), patch("sentry_sdk.init", side_effect=ValueError("bad dsn")), \
                self.assertLogs("modules.alerts", "WARNING"):
            self.assertFalse(alerts.init_sentry())

    def test_before_send_drops_requests_and_scrubs(self):
        event = {
            "request": {"url": "https://bot.example/hook", "data": "student text"},
            "user": {"id": 5},
            "extra": {"sys.argv": ["x"]},
            "exception": {"values": [{
                "type": "ValueError", "value": f"failed for {config.TOKEN} " + "x" * 1000,
                "stacktrace": {"frames": [{"filename": "a.py", "vars": {"text": "what the student typed"}}]},
            }]},
            "breadcrumbs": {"values": [
                {"category": "httplib", "data": {"url": f"https://api.telegram.org/bot{REAL_LOOKING_TOKEN}/getMe"}},
                {"category": "telegram.ext", "message": f"using {REAL_LOOKING_TOKEN}"},
            ]},
            "logentry": {"message": f"Error with {config.TOKEN}"},
        }
        cleaned = alerts.before_send(event, {})
        for key in ("request", "user", "extra"):
            self.assertNotIn(key, cleaned)
        value = cleaned["exception"]["values"][0]
        self.assertTrue(value["value"].startswith("failed for [redacted] xxx"))
        self.assertLessEqual(len(value["value"]), alerts.MAX_TEXT_CHARS)
        self.assertNotIn("vars", value["stacktrace"]["frames"][0])
        self.assertEqual(cleaned["breadcrumbs"]["values"], [{"category": "telegram.ext", "message": "using [redacted]"}])
        self.assertEqual(cleaned["logentry"]["message"], "Error with [redacted]")

    def test_the_real_sdk_sends_nothing_secret(self):
        """Sentry with a transport that keeps the envelopes instead of sending them."""
        import sentry_sdk
        from sentry_sdk.transport import Transport

        envelopes = []

        class KeepTransport(Transport):
            def capture_envelope(self, envelope):
                envelopes.append(envelope)

        with patch.object(config, "SENTRY_DSN", "https://key@o1.ingest.sentry.io/2"):
            real_init = sentry_sdk.init
            with patch("sentry_sdk.init", side_effect=lambda **options: real_init(transport=KeepTransport, **options)):
                self.assertTrue(alerts.init_sentry())
        try:
            log = logging.getLogger("modules.sentry_test")
            log.info("Ignored /stats from user id %s", 42)  # INFO: no breadcrumb at all
            log.warning("Retrying https://api.telegram.org/bot%s/sendMessage", REAL_LOOKING_TOKEN)
            try:
                raise RuntimeError(f"failed with {config.TOKEN}")
            except RuntimeError:
                log.exception("Error while handling an update")
            sentry_sdk.flush(2)
        finally:
            sentry_sdk.get_client().close()
            sentry_sdk.init()  # no DSN: off again for the other tests
        payload = "".join(item.payload.get_bytes().decode("utf-8", "replace") for envelope in envelopes for item in envelope.items)
        self.assertIn("RuntimeError", payload)
        self.assertIn("[redacted]", payload)
        (event,) = [item.payload.json for envelope in envelopes for item in envelope.items if item.type == "event"]
        self.assertEqual(event["exception"]["values"][0]["value"], "failed with [redacted]")
        # Only the warning became a breadcrumb (INFO lines hold user ids), scrubbed.
        self.assertEqual([crumb["message"] for crumb in event["breadcrumbs"]["values"]],
                         ["Retrying https://api.telegram.org/bot[redacted]/sendMessage"])
        self.assertNotIn("request", event)
        self.assertNotIn("user", event)
        for secret in (config.TOKEN, REAL_LOOKING_TOKEN):
            self.assertNotIn(secret, payload)
