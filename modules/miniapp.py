"""The Mini App's server side, without web or Telegram objects: who is calling (Telegram's signed launch data),
and the reachability test's measurements.

Identity: the page sends Telegram's launch data (initData) with every request. check_init_data() verifies it
with the bot token, as Telegram documents it (https://core.telegram.org/bots/webapps, "Validating data received
via the Mini App"):
- data_check_string: every field except hash, as key=value (URL-decoded), sorted by key, joined by "\\n";
- secret_key = HMAC-SHA256(key="WebAppData", message=bot token);
- the hash must be hex(HMAC-SHA256(key=secret_key, message=data_check_string)), compared in constant time;
- auth_date older than MINIAPP_AUTH_MAX_AGE_SECONDS (or more than a minute in the future) is refused.
Only the user id (and the language code, start parameter and platform) is used. The name, username and photo
in the launch data are never stored or logged.

Measurements (step 1, the reachability test): each time the page opens it reports how long it took to load;
a tester who tapped "❌ It didn't open" is recorded as a failed open. darsai_miniapp_ping (migration 2) keeps
the day, the user id (so Delete my data removes it), the device type and the timings, nothing else.

All storage functions are blocking. Call them with asyncio.to_thread.
"""

import hashlib
import hmac
import itertools
import json
import threading
import time
from datetime import date, timedelta
from statistics import median
from typing import Dict, Iterable, Optional, Tuple
from urllib.parse import parse_qsl

from modules.activity import utc_today
from modules.db import connection, db_configured

# The device types Telegram reports (tgWebAppPlatform); anything else is stored as "other".
PLATFORMS = ("android", "android_x", "ios", "tdesktop", "macos", "weba", "webk", "web", "unigram", "unknown")
TIMING_FIELDS = ("dns_ms", "connect_ms", "ttfb_ms", "dom_ms", "total_ms", "api_ms")
MAX_TIMING_MS = 600_000
# Clock differences between Telegram's servers and this one.
FUTURE_TOLERANCE_SECONDS = 60

# In-memory fallback, used only when DATABASE_URL is not set: {(user_id, n): row}
_FALLBACK: Dict[Tuple[int, int], Dict] = {}
_LOCK = threading.Lock()
_counter = itertools.count(1)


# ------------------------------------------------------------
# Telegram's launch data
# ------------------------------------------------------------

def check_init_data(init_data: str, bot_token: str, max_age_seconds: int, now: Optional[float] = None) -> Optional[Dict]:
    """{"user_id", "language_code", "start_param"} when init_data is genuine and fresh, else None."""
    if not init_data or not bot_token or len(init_data) > 8192:
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    fields = dict(pairs)
    if len(fields) != len(pairs):
        return None  # a field given twice: refuse rather than guess which one was signed
    received = fields.pop("hash", "")
    if not received:
        return None
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received.lower()):
        return None
    try:
        auth_date = int(fields.get("auth_date", ""))
        user = json.loads(fields.get("user", ""))
        user_id = int(user["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    now = time.time() if now is None else now
    if now - auth_date > max_age_seconds or auth_date - now > FUTURE_TOLERANCE_SECONDS:
        return None
    language = user.get("language_code") if isinstance(user.get("language_code"), str) else None
    return {"user_id": user_id, "language_code": language, "start_param": fields.get("start_param") or None}


# ------------------------------------------------------------
# Measurements
# ------------------------------------------------------------

def clean_ping(payload: Dict) -> Dict:
    """Only the expected fields, as small numbers and known words. Anything else the page sends is dropped."""
    platform = str(payload.get("platform", "unknown"))[:20].lower()
    row = {"platform": platform if platform in PLATFORMS else "other", "bridge": bool(payload.get("bridge"))}
    for field in TIMING_FIELDS:
        value = payload.get(field)
        row[field] = int(min(max(value, 0), MAX_TIMING_MS)) if isinstance(value, (int, float)) and value == value else None
    return row


def record_open(user_id: int, payload: Dict) -> None:
    """The page opened: save its load timings."""
    _save(user_id, dict(clean_ping(payload), opened=True))


def record_failure(user_id: int) -> None:
    """A tester tapped "❌ It didn't open"."""
    _save(user_id, {"opened": False, "platform": None, "bridge": None, **{field: None for field in TIMING_FIELDS}})


def _save(user_id: int, row: Dict) -> None:
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO darsai_miniapp_ping
                    (user_id, day, opened, platform, bridge, dns_ms, connect_ms, ttfb_ms, dom_ms, total_ms, api_ms)
                VALUES (%(user_id)s, %(day)s, %(opened)s, %(platform)s, %(bridge)s, %(dns_ms)s, %(connect_ms)s,
                        %(ttfb_ms)s, %(dom_ms)s, %(total_ms)s, %(api_ms)s)
            """, dict(row, user_id=user_id, day=utc_today()))
        return
    with _LOCK:
        _FALLBACK[(user_id, next(_counter))] = dict(row, day=utc_today())


def ping_summary(today: date, exclude: Iterable[int] = ()) -> Dict:
    """For /stats: today's and the last 7 days' opens, testers, median load time and failures. Admins left out."""
    exclude = sorted(set(exclude))
    week = today - timedelta(days=6)
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT day, user_id, opened, total_ms FROM darsai_miniapp_ping
                WHERE day >= %(week)s AND user_id <> ALL(%(exclude)s::bigint[])
            """, {"week": week, "exclude": exclude})
            rows = [{"day": d, "user_id": u, "opened": o, "total_ms": t} for d, u, o, t in cur.fetchall()]
    else:
        with _LOCK:
            rows = [dict(row, user_id=uid) for (uid, _), row in _FALLBACK.items() if uid not in exclude and row["day"] >= week]

    def period(selected):
        opens = [row for row in selected if row["opened"]]
        times = [row["total_ms"] for row in opens if row["total_ms"] is not None]
        return {
            "opens": len(opens),
            "testers": len({row["user_id"] for row in opens}),
            "median_ms": int(median(times)) if times else None,
            "failures": sum(1 for row in selected if not row["opened"]),
        }

    return {"today": period([row for row in rows if row["day"] == today]), "week": period(rows)}
