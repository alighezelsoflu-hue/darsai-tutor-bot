"""/stats for admins (ADMIN_USER_IDS), and the tracker that notes which students use the bot each day.

Where the numbers come from (days are UTC, like the daily tutor limit):
- Active students: darsai_daily_activity (anyone who sent the bot a message or pressed its buttons), plus
  students who used the tutor (darsai_ai_usage) or practised (darsai_mastery) before that table existed.
  All time counts everyone the bot has any record of.
- Practice answers: per day from darsai_daily_activity, all time from darsai_mastery.
- Tutor messages and students who hit the daily limit: darsai_ai_usage.
- The Premium waitlist: darsai_premium_waitlist.

/stats is English only: students never see it.
"""

import asyncio
import logging
from datetime import date, timedelta
from typing import Dict, Optional, Set

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, ContextTypes, TypeHandler

from config import ADMIN_USER_IDS, ADMIN_USER_IDS_IGNORED, BOT_NAME, FREE_DAILY_AI_LIMIT
from modules import activity, ai, premium, student
from modules.db import connection, db_configured
from modules.i18n import t
from modules.math import shared

logger = logging.getLogger(__name__)

WEEK_DAYS = 7


# ------------------------------------------------------------
# Who used the bot today
# ------------------------------------------------------------

# Students already noted today by this process, so each student costs one database write a day.
_seen_day: Optional[date] = None
_seen: Set[int] = set()


def counts_as_activity(update: Update) -> bool:
    """A button press, or a message a student sent to the bot. Not the bot being added or blocked."""
    user = update.effective_user
    if user is None or user.is_bot:
        return False
    if update.callback_query is not None:
        return True
    message = update.message
    if message is None or message.sender_chat is not None:
        return False  # e.g. an edited message, or a post as the group or a channel
    if message.chat.type == ChatType.PRIVATE:
        return True
    # In groups the bot sees commands and replies to its own messages (privacy mode).
    return (message.text or "").startswith("/") or message.reply_to_message is not None


async def track_activity(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs before every other handler. Never stops the update, and a failure is only logged."""
    global _seen_day
    if not isinstance(update, Update) or not counts_as_activity(update):
        return
    day = activity.utc_today()
    if day != _seen_day:
        _seen_day = day
        _seen.clear()
    user_id = update.effective_user.id
    if user_id in _seen:
        return
    try:
        await asyncio.to_thread(activity.mark_active, user_id, day)
    except Exception as error:
        logger.warning("Could not save today's activity: %s", error)
        return
    _seen.add(user_id)


# ------------------------------------------------------------
# The numbers
# ------------------------------------------------------------

def collect_stats(today: date) -> Dict:
    """Blocking. Every number /stats shows."""
    week = today - timedelta(days=WEEK_DAYS - 1)
    limit = FREE_DAILY_AI_LIMIT
    stats = {"today": today, "week": week, "limit": limit, "waitlist": premium.waitlist_summary()}
    if db_configured():
        stats.update(_collect_from_database(today, week, limit))
    else:
        stats.update(_collect_from_memory(today, week, limit))
    return stats


def _collect_from_database(today: date, week: date, limit: int) -> Dict:
    active_since = """
        SELECT COUNT(*) FROM (
            SELECT user_id FROM darsai_daily_activity WHERE day >= %(start)s
            UNION SELECT user_id FROM darsai_ai_usage WHERE day >= %(start)s
            UNION SELECT user_id FROM darsai_mastery WHERE updated_at >= (%(start)s::timestamp AT TIME ZONE 'UTC')
        ) AS active
    """
    with connection() as conn, conn.cursor() as cur:
        active = {}
        for name, start in (("today", today), ("week", week)):
            cur.execute(active_since, {"start": start})
            active[name] = cur.fetchone()[0]
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT user_id FROM darsai_daily_activity
                UNION SELECT user_id FROM darsai_ai_usage
                UNION SELECT user_id FROM darsai_mastery
                UNION SELECT user_id FROM darsai_student
                UNION SELECT user_id FROM darsai_user_profile
                UNION SELECT user_id FROM darsai_ai_messages
                UNION SELECT user_id FROM darsai_premium_waitlist
            ) AS everyone
        """)
        active["total"] = cur.fetchone()[0]

        cur.execute("""
            SELECT COALESCE(SUM(practice_answers) FILTER (WHERE day = %(today)s), 0),
                   COALESCE(SUM(practice_answers) FILTER (WHERE day >= %(week)s), 0),
                   MIN(day)
            FROM darsai_daily_activity
        """, {"today": today, "week": week})
        practice_today, practice_week, counting_since = cur.fetchone()
        cur.execute("SELECT COALESCE(SUM(correct_count + wrong_count), 0) FROM darsai_mastery")
        practice_total = cur.fetchone()[0]

        cur.execute("""
            SELECT COALESCE(SUM(count) FILTER (WHERE day = %(today)s), 0),
                   COALESCE(SUM(count) FILTER (WHERE day >= %(week)s), 0),
                   COALESCE(SUM(count), 0),
                   COUNT(*) FILTER (WHERE day = %(today)s AND %(limit)s > 0 AND count >= %(limit)s)
            FROM darsai_ai_usage
        """, {"today": today, "week": week, "limit": limit})
        tutor_today, tutor_week, tutor_total, limit_hits = cur.fetchone()

    return {
        "active": active,
        "practice": {"today": practice_today, "week": practice_week, "total": practice_total},
        "tutor": {"today": tutor_today, "week": tutor_week, "total": tutor_total},
        "limit_hits": limit_hits,
        "counting_since": counting_since,
    }


def _collect_from_memory(today: date, week: date, limit: int) -> Dict:
    """The same numbers from the in-memory fallbacks (local testing without a database)."""
    days = dict(activity._FALLBACK)
    usage = dict(ai._USAGE_FALLBACK)  # only today: older days are dropped from memory
    mastery = dict(shared.MASTERY_FALLBACK)

    def active_since(start: date) -> int:
        users = {uid for (day, uid) in days if day >= start} | {uid for (uid, day) in usage if day >= start}
        return len(users)

    everyone = (
        {uid for (_, uid) in days} | {uid for (uid, _) in usage} | {uid for (uid, _, _) in mastery}
        | set(student._FALLBACK) | {uid for (_, uid, _) in ai._MEMORY_FALLBACK} | {uid for (uid, _) in premium._FALLBACK}
    )
    return {
        "active": {"today": active_since(today), "week": active_since(week), "total": len(everyone)},
        "practice": {
            "today": sum(row["practice_answers"] for (day, _), row in days.items() if day == today),
            "week": sum(row["practice_answers"] for (day, _), row in days.items() if day >= week),
            "total": sum(int(entry["correct"] + entry["wrong"]) for entry in mastery.values()),
        },
        "tutor": {
            "today": sum(count for (_, day), count in usage.items() if day == today),
            "week": sum(count for (_, day), count in usage.items() if day >= week),
            "total": sum(usage.values()),
        },
        "limit_hits": sum(1 for (_, day), count in usage.items() if day == today and 0 < limit <= count),
        "counting_since": min((day for (day, _) in days), default=None),
    }


def _students(count: int) -> str:
    return f"{count:,} student" + ("" if count == 1 else "s")


def format_stats(stats: Dict) -> str:
    def periods(numbers: Dict) -> str:
        return f"Today: {numbers['today']:,} · Last {WEEK_DAYS} days: {numbers['week']:,} · All time: {numbers['total']:,}"

    waitlist = stats["waitlist"]
    sources = waitlist["sources"]
    lines = [
        f"📊 {BOT_NAME} stats · {stats['today'].isoformat()} (UTC)",
        "",
        "👥 Active students",
        periods(stats["active"]),
        "",
        "✍️ Practice answers",
        periods(stats["practice"]),
        "",
        "🧑‍🏫 Tutor messages",
        periods(stats["tutor"]),
        "",
        f"⏳ Hit the daily limit today: {_students(stats['limit_hits'])} (limit {stats['limit']})"
        if stats["limit"] > 0 else "⏳ There is no daily tutor limit (FREE_DAILY_AI_LIMIT).",
        "",
        f"💎 Premium waitlist: {_students(waitlist['students'])}",
        f"From 💎 Premium: {sources['menu']:,} · From the limit message: {sources['limit']:,}",
    ]
    lines += [f"{t('en', f'premium.choice.{choice}')}: {count:,}" for choice, count in waitlist["choices"].items()]
    since = stats["counting_since"] or stats["today"]
    if since > stats["week"]:
        lines += [
            "",
            f"Counting by day started {since.isoformat()}. Before that, active students only include tutor "
            "and practice use, and practice answers are only in All time.",
        ]
    return "\n".join(lines)


# ------------------------------------------------------------
# /stats
# ------------------------------------------------------------

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message, user, chat = update.effective_message, update.effective_user, update.effective_chat
    if not message or not user or not chat:
        return
    if user.id not in ADMIN_USER_IDS or chat.type != ChatType.PRIVATE:
        # No reply, like any unknown command. The log line is how an admin finds their own user id.
        logger.info(
            "Ignored /stats from user id %s in a %s chat (it needs a private chat and a user id in ADMIN_USER_IDS).",
            user.id, chat.type,
        )
        return
    stats = await asyncio.to_thread(collect_stats, activity.utc_today())
    await message.reply_text(format_stats(stats))


def log_admin_setting() -> None:
    """A typo in ADMIN_USER_IDS must never stop the bot, so it is only reported here."""
    for part in ADMIN_USER_IDS_IGNORED:
        logger.warning("ADMIN_USER_IDS: ignored %r, because it isn't a Telegram user id (a number).", part)
    logger.info("/stats is available to %d admin user id(s) from ADMIN_USER_IDS.", len(ADMIN_USER_IDS))


def register_stats_handlers(app: Application) -> None:
    log_admin_setting()
    # Before everything else (group -2), so every update is seen even when a later handler stops it.
    app.add_handler(TypeHandler(Update, track_activity), group=-2)
    app.add_handler(CommandHandler("stats", stats_command))
