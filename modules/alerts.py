"""Error alerts: every ERROR in the log goes to the admins (ADMIN_USER_IDS) on Telegram, and to Sentry when
SENTRY_DSN is set.

What an alert contains, for both:
- The kind of error, where in our code it happened (file, line, function), the log message and the
  exception's message, cut to MAX_TEXT_CHARS.
- Never the update (what the student sent or pressed), local variables, request bodies or headers.
- Every secret is replaced with [redacted] (scrub): the bot token (and anything shaped like a bot token,
  because Telegram API URLs contain it), the webhook secret and path, the AI API keys, the database URL and
  any password in a URL, and the Sentry DSN.
An exception's message can still contain a few characters a student typed (e.g. "Unknown name: abc" from a
formula), which is why it is cut short.

Telegram alerts are grouped: the same kind of error (logger, message template, exception type and place)
goes out at most once per ALERT_REPEAT_MINUTES, and the next alert of that kind says how many were held
back. At most MAX_ALERTS_PER_WINDOW alerts of all kinds go out per window. Alerts are sent by the bot
itself, so they come from the bot that had the error (production, staging or the local test bot).

A failure to send an alert is logged at WARNING by this module, and nothing this module logs, or anything
logged while an alert is being sent, ever becomes an alert, so alerts can't loop.

A moment without Telegram (NetworkError, TimedOut) or its flood control (RetryAfter) is no alert: the library
retries, or the next update works, and nobody can act on it. main.error_handler logs it as one WARNING line
(is_connection_blip, blip_text). Only NETWORK_ALERT_THRESHOLD of them within NETWORK_ALERT_WINDOW_MINUTES
(connection_blips, per process) are logged as one ERROR, "Telegram unreachable", which is alerted as usual.

The console log (stdout and stderr, which is Render's log) is scrubbed the same way: scrub_console_logs()
wraps the formatter of every handler on the root and uvicorn loggers, and of uncaught exceptions, so no
secret reaches it by any path, tracebacks included.

/alerttest (admins only, the same check as /stats) raises a test error to check all of this.
"""

import asyncio
import contextvars
import logging
import re
import sys
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional, Set, Tuple

from telegram import Update
from telegram.error import BadRequest, NetworkError, RetryAfter
from telegram.ext import Application, CommandHandler, ContextTypes

import config
from config import BOT_NAME
from modules.admin import admin_command

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 300
MAX_ALERTS_PER_WINDOW = 10
REDACTED = "[redacted]"
PROJECT_ROOT = Path(config.__file__).resolve().parent

# Anything shaped like a bot token: the bot id, a colon, then the secret part.
BOT_TOKEN_PATTERN = re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}")
# user:password@ in a URL (e.g. a database URL).
URL_PASSWORD_PATTERN = re.compile(r"([a-z][a-z0-9+.-]*://[^:/?#\s@]*:)[^@\s/]+@", re.IGNORECASE)
# Breadcrumbs of outgoing HTTP requests: their URLs contain the bot token or API paths.
HTTP_BREADCRUMB_CATEGORIES = {"httplib", "httpx", "http", "requests", "urllib3"}

# /alerttest puts this in its error: it looks like a bot token, so the alert and the log must show [redacted].
FAKE_TOKEN = "123456789:ThisIsNotARealTokenItOnlyLooksLikeOne"

# Set while an alert is being sent: anything logged meanwhile (e.g. by the Telegram library) is no alert.
_sending: contextvars.ContextVar[bool] = contextvars.ContextVar("darsai_alert_sending", default=False)


def _secrets() -> List[str]:
    values = {
        config.TOKEN, config.WEBHOOK_SECRET_TOKEN, config.GROQ_API_KEY, config.OPENROUTER_API_KEY,
        config.OPENAI_API_KEY, config.DATABASE_URL, config.SENTRY_DSN,
    }
    # The webhook path is a secret too, unless it is the default everyone can read in the code.
    if config.SECRET_PATH and config.SECRET_PATH != "darsai-webhook":
        values.add(config.SECRET_PATH)
    # Longest first, so a secret that contains another is replaced whole.
    return sorted((value for value in values if value and len(value) >= 8), key=len, reverse=True)


def scrub(text: str) -> str:
    """The text with every secret replaced by [redacted]."""
    text = str(text)
    for secret in _secrets():
        text = text.replace(secret, REDACTED)
    text = BOT_TOKEN_PATTERN.sub(REDACTED, text)
    return URL_PASSWORD_PATTERN.sub(rf"\1{REDACTED}@", text)


def shorten(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _relative(filename: str) -> Optional[str]:
    """The path inside the project, or None for the standard library and installed packages."""
    path = Path(filename).resolve()
    if "site-packages" in path.parts or ".venv" in path.parts:
        return None
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return None


def _library(filename: str) -> str:
    """Whose code a file outside the project is: "the telegram library" (an installed package) or Python's own."""
    parts = Path(filename).parts
    for marker in ("site-packages", "dist-packages"):
        if marker in parts[:-1]:
            return f"the {Path(parts[parts.index(marker) + 1]).stem} library"
    return "Python's standard library"


def _where(record: logging.LogRecord) -> str:
    """The last place in our own code: where the exception was raised, else where it was logged.

    An exception raised without any of our code on the way (e.g. polling Telegram) names the library instead, then
    where it was logged, so the alert doesn't point at the error handler as if the error were there.
    """
    logged_at = f"{_relative(record.pathname) or Path(record.pathname).name}:{record.lineno} in {record.funcName}"
    if record.exc_info and record.exc_info[2] is not None:
        frames = traceback.extract_tb(record.exc_info[2])
        for frame in reversed(frames):
            path = _relative(frame.filename)
            if path:
                return f"{path}:{frame.lineno} in {frame.name}"
        if frames:
            return f"inside {_library(frames[-1].filename)} (no {BOT_NAME} code); logged at {logged_at}"
    return logged_at


def describe(record: logging.LogRecord) -> Tuple[Tuple[str, ...], List[str]]:
    """(kind, lines) for a log record. Everything in the lines is scrubbed and cut short."""
    error = record.exc_info[1] if record.exc_info else None
    where = _where(record)
    template = record.msg if isinstance(record.msg, str) else type(record.msg).__name__
    kind = (record.name, template, type(error).__name__ if error else "", where)
    lines = [f"🚨 {BOT_NAME} error"]
    if error is not None:
        lines.append(shorten(scrub(f"{type(error).__name__}: {error}")))
    lines.append("Where: " + where)
    try:
        message = record.getMessage()
    except Exception:
        message = template
    lines.append(shorten(scrub(f"Log ({record.name}): {message}")))
    lines.append(datetime.fromtimestamp(record.created, timezone.utc).strftime("Time: %Y-%m-%d %H:%M UTC"))
    return kind, lines


# ------------------------------------------------------------
# The console log
# ------------------------------------------------------------

class ScrubbingFormatter(logging.Formatter):
    """Wraps a handler's formatter: the whole formatted record, traceback included, goes through scrub()."""

    def __init__(self, inner: Optional[logging.Formatter] = None):
        super().__init__()
        self.inner = inner or logging.Formatter()

    def format(self, record: logging.LogRecord) -> str:
        return scrub(self.inner.format(record))


def _print_scrubbed(exc_type, exc, tb) -> None:
    sys.stderr.write(scrub("".join(traceback.format_exception(exc_type, exc, tb))))


def scrub_console_logs() -> None:
    """Scrub everything the console handlers print, and uncaught exceptions. Idempotent.

    Call right after logging is set up and before init_sentry (Sentry wraps the exception hook it finds).
    """
    for name in ("", "uvicorn", "uvicorn.access", "uvicorn.error"):
        for handler in logging.getLogger(name).handlers:
            if handler is not admin_alerts and not isinstance(handler.formatter, ScrubbingFormatter):
                handler.setFormatter(ScrubbingFormatter(handler.formatter))
    sys.excepthook = _print_scrubbed
    threading.excepthook = lambda args: _print_scrubbed(args.exc_type, args.exc_value, args.exc_traceback)


# ------------------------------------------------------------
# Telegram alerts to the admins
# ------------------------------------------------------------

class AdminAlerts(logging.Handler):
    """A logging handler that sends ERROR records to the admins, grouped (see the module docstring)."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self._lock = threading.Lock()
        self._bot = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tasks: Set[asyncio.Task] = set()
        self._kinds: Dict[Tuple[str, ...], Dict] = {}  # kind -> {"sent": time, "held": count}
        self._window_start = 0.0
        self._window_sent = 0
        self._window_held = 0

    @property
    def window_seconds(self) -> float:
        return config.ALERT_REPEAT_MINUTES * 60

    def start(self, bot) -> None:
        """Begin sending (call from the event loop, once the bot is initialized)."""
        self._bot = bot
        self._loop = asyncio.get_running_loop()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self._bot is None or self._loop is None or record.name.startswith(__name__) or _sending.get():
                return
            admins = sorted(config.ADMIN_USER_IDS)
            if not admins or not config.ALERTS_TO_ADMINS:
                return
            kind, lines = describe(record)
            text = self._admit(kind, lines, time.time())
            if text is not None and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._spawn, admins, text)
        except Exception:
            # Never let an alert problem reach the code that logged the error.
            pass

    def _admit(self, kind: Tuple[str, ...], lines: List[str], now: float) -> Optional[str]:
        """The alert's text when it may go out now, else None (it is counted for the next alert)."""
        with self._lock:
            if now - self._window_start >= self.window_seconds:
                self._window_start, self._window_sent = now, 0
            entry = self._kinds.get(kind)
            if entry is not None and now - entry["sent"] < self.window_seconds:
                entry["held"] += 1
                return None
            if self._window_sent >= MAX_ALERTS_PER_WINDOW:
                self._window_held += 1
                return None
            held = entry["held"] if entry else 0
            self._kinds[kind] = {"sent": now, "held": 0}
            self._window_sent += 1
            extra = []
            if held:
                extra.append(f"+{held} more like this since the last alert (at most one per {config.ALERT_REPEAT_MINUTES} min).")
            if self._window_held:
                extra.append(f"+{self._window_held} other errors were not sent (at most {MAX_ALERTS_PER_WINDOW} alerts per {config.ALERT_REPEAT_MINUTES} min).")
                self._window_held = 0
            return "\n".join(lines + extra)

    def _spawn(self, admins: List[int], text: str) -> None:
        task = asyncio.ensure_future(self._send(admins, text))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _send(self, admins: List[int], text: str) -> None:
        _sending.set(True)
        for admin in admins:
            try:
                await self._bot.send_message(admin, text)
            except Exception as error:
                # WARNING, from this module: never an alert itself.
                logger.warning("Could not send an error alert to admin %s: %s", admin, shorten(scrub(error), 120))

    async def drain(self) -> None:
        """Wait for the alerts being sent (at shutdown, and in tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def reset(self) -> None:
        """Forget the grouping (tests)."""
        with self._lock:
            self._kinds.clear()
            self._window_start = self._window_sent = self._window_held = 0


admin_alerts = AdminAlerts()


# ------------------------------------------------------------
# Telegram connection blips (main.error_handler)
# ------------------------------------------------------------

def is_connection_blip(error: Optional[BaseException]) -> bool:
    """A moment without Telegram (NetworkError, and TimedOut, a kind of it) or its flood control (RetryAfter).

    BadRequest is a NetworkError in python-telegram-bot too, but it is a mistake in our request (e.g. a message
    that can't be edited any more), so it stays a normal error.
    """
    if isinstance(error, RetryAfter):
        return True
    return isinstance(error, NetworkError) and not isinstance(error, BadRequest)


def blip_text(error: BaseException) -> str:
    """E.g. "httpx.ReadError" (python-telegram-bot puts the httpx error in a NetworkError's message) or
    "TimedOut: Timed out". Scrubbed and cut short."""
    name = type(error).__name__
    message = str(error).strip().rstrip(":").strip()
    if not message:
        text = name
    elif name == "NetworkError":
        text = message
    else:
        text = f"{name}: {message}"
    return shorten(scrub(text), 120)


class BurstCounter:
    """Per process: when the recent events of one kind were, to tell a few from too many (e.g. Telegram connection
    blips from Telegram being unreachable). The threshold and the window are read from config by name, so tests
    and settings can change them."""

    def __init__(self, threshold_setting: str, window_minutes_setting: str) -> None:
        self.threshold_setting, self.window_minutes_setting = threshold_setting, window_minutes_setting
        self._lock = threading.Lock()
        self._times: Deque[float] = deque(maxlen=10_000)
        self._last_alarm: Optional[float] = None

    @property
    def window_minutes(self) -> int:
        return getattr(config, self.window_minutes_setting)

    def note(self) -> Tuple[int, bool]:
        """(events within the window, this one included; whether to log the one ERROR now).

        True when there are as many as the threshold, at most once per window: while the trouble lasts, the ERROR
        comes again each window (and the alert grouping holds back the repeats as usual).
        """
        now = time.time()
        window = self.window_minutes * 60
        with self._lock:
            self._times.append(now)
            while now - self._times[0] >= window:
                self._times.popleft()
            count = len(self._times)
            alarm = count >= getattr(config, self.threshold_setting) and (
                self._last_alarm is None or now - self._last_alarm >= window
            )
            if alarm:
                self._last_alarm = now
            return count, alarm

    def reset(self) -> None:
        """Forget the events (tests)."""
        with self._lock:
            self._times.clear()
            self._last_alarm = None


connection_blips = BurstCounter("NETWORK_ALERT_THRESHOLD", "NETWORK_ALERT_WINDOW_MINUTES")


def install_log_handler() -> None:
    """Attach the alert handler to the root logger and to uvicorn's (which doesn't pass records up). Idempotent."""
    for name in ("", "uvicorn"):
        target = logging.getLogger(name)
        if admin_alerts not in target.handlers:
            target.addHandler(admin_alerts)


async def start_alerts(bot) -> None:
    """At startup, once the bot is initialized: start the Telegram alerts and report the settings."""
    install_log_handler()
    admin_alerts.start(bot)
    for warning in config.SETTING_WARNINGS:
        logger.warning("Setting ignored: %s", warning)
    if config.ALERTS_TO_ADMINS and config.ADMIN_USER_IDS:
        logger.info("Errors are sent to %d admin(s) on Telegram, each kind at most once per %d min.",
                    len(config.ADMIN_USER_IDS), config.ALERT_REPEAT_MINUTES)
    else:
        logger.info("Error alerts on Telegram are off (ALERTS_TO_ADMINS, or no ADMIN_USER_IDS).")


async def stop_alerts() -> None:
    await admin_alerts.drain()


# ------------------------------------------------------------
# Sentry (optional)
# ------------------------------------------------------------

def _scrub_tree(value, cut: bool = False):
    if isinstance(value, str):
        value = scrub(value)
        return shorten(value) if cut else value
    if isinstance(value, dict):
        return {key: _scrub_tree(item, cut) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub_tree(item, cut) for item in value]
    return value


def before_send(event: Dict, hint: Dict) -> Optional[Dict]:
    """Sentry: drop what could hold student text or secrets, scrub everything else."""
    for key in ("request", "user", "extra"):
        event.pop(key, None)
    for exception in (event.get("exception") or {}).get("values") or []:
        if "value" in exception:
            exception["value"] = shorten(scrub(exception["value"]))
        for frame in (exception.get("stacktrace") or {}).get("frames") or []:
            frame.pop("vars", None)
    crumbs = (event.get("breadcrumbs") or {}).get("values")
    if crumbs is not None:
        event["breadcrumbs"]["values"] = [crumb for crumb in crumbs if before_breadcrumb(crumb, {}) is not None]
    return _scrub_tree(event)


def before_breadcrumb(crumb: Dict, hint: Dict) -> Optional[Dict]:
    """Sentry: no breadcrumbs of HTTP requests (their URLs contain the bot token); scrub the rest."""
    if crumb.get("category") in HTTP_BREADCRUMB_CATEGORIES or crumb.get("type") == "http":
        return None
    if str(crumb.get("category", "")).startswith("httpx"):
        return None
    return _scrub_tree(crumb, cut=True)


def init_sentry() -> bool:
    """Start Sentry when SENTRY_DSN is set. The SDK is only imported then, so it costs nothing while off."""
    if not config.SENTRY_DSN:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=config.SENTRY_DSN,
            environment=config.SENTRY_ENVIRONMENT,
            # Nothing about the student, no request data, no local variables (they hold what students sent).
            data_collection={
                "user_info": False,
                "cookies": {"mode": "off"},
                "http_headers": {"request": {"mode": "off"}},
                "http_bodies": [],
                "url_query_params": {"mode": "off"},
                "gen_ai": {"inputs": False, "outputs": False},
                "database_query_data": False,
                "queues": False,
                "stack_frame_variables": False,
            },
            include_local_variables=False,
            max_request_body_size="never",
            traces_sample_rate=0,
            # Integrations that hook into installed libraries (httpx, FastAPI, …) stay off: they would record
            # request URLs (with the bot token) and webhook bodies (what students sent).
            auto_enabling_integrations=False,
            # Warnings become breadcrumbs, errors events. Not INFO: those lines hold user ids.
            integrations=[LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR)],
            before_send=before_send,
            before_breadcrumb=before_breadcrumb,
        )
    except Exception as error:
        logger.warning("Could not start Sentry, so errors only go to the log: %s", shorten(scrub(error), 200))
        return False
    logger.info("Sentry is on (environment %s).", config.SENTRY_ENVIRONMENT)
    return True


# ------------------------------------------------------------
# /alerttest
# ------------------------------------------------------------

class AlertTestError(RuntimeError):
    """Raised on purpose by /alerttest."""


async def alerttest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not admin_command(update, "alerttest"):
        return
    await update.effective_message.reply_text(
        "Raising a test error now. Each admin should get an alert in a few seconds. In it, the token check must "
        "say [redacted]. A second /alerttest within ALERT_REPEAT_MINUTES is held back and counted."
    )
    # A fake value shaped like a bot token (never the real one): the alert and the log must both scrub it.
    raise AlertTestError(f"This is a test error from /alerttest (token check: {FAKE_TOKEN})")


def register_alert_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("alerttest", alerttest_command))
