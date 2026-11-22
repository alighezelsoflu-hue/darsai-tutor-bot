"""/stats for admins (ADMIN_USER_IDS), and the tracker that notes which students use the bot each day.

Where the numbers come from (days are UTC, like the daily tutor limit). Admins are left out of all of them.
- Active students: darsai_daily_activity (anyone who sent the bot a message or pressed its buttons), plus
  students who used the tutor (darsai_ai_usage) or practised (darsai_mastery) before that table existed.
  All time counts everyone the bot has any record of.
- New students and their start link: darsai_first_seen.
- Practice answers: per day from darsai_daily_activity, all time from darsai_mastery.
- Tutor messages and students who hit the daily limit: darsai_ai_usage.
- The Premium waitlist: darsai_premium_waitlist.
- 🔔 Notify me on the coming-soon courses: darsai_course_notify.

/stats is English only: students never see it.
"""

import asyncio
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, ContextTypes, TypeHandler

from config import ADMIN_USER_IDS, ADMIN_USER_IDS_IGNORED, BOT_NAME, FREE_DAILY_AI_LIMIT
from modules import activity, ai, notify, premium, student
from modules.courses import COURSES
from modules.db import connection, db_configured
from modules.i18n import t
from modules.math import shared

logger = logging.getLogger(__name__)

WEEK_DAYS = 7
# /stats lists the start links with the most new students; the rest are added up in one line.
MAX_SOURCES = 15


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


def start_link_source(update: Update) -> Optional[str]:
    """The source of a start link (t.me/<bot>?start=<source> sends "/start <source>" in a private chat)."""
    message = update.message
    if message is None or message.chat.type != ChatType.PRIVATE:
        return None
    parts = (message.text or "").split()
    if len(parts) != 2 or parts[0].split("@", 1)[0] != "/start":
        return None
    return activity.valid_source(parts[1])


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
        # Seen today already, so not new: a start link can't give them a source any more.
        return
    try:
        await asyncio.to_thread(activity.mark_active, user_id, day, start_link_source(update))
    except Exception as error:
        logger.warning("Could not save today's activity: %s", error)
        return
    _seen.add(user_id)


# ------------------------------------------------------------
# The numbers
# ------------------------------------------------------------

def collect_stats(today: date, admins=ADMIN_USER_IDS) -> Dict:
    """Blocking. Every number /stats shows, without the admins in it."""
    week = today - timedelta(days=WEEK_DAYS - 1)
    limit = FREE_DAILY_AI_LIMIT
    admins = sorted(set(admins))
    stats = {
        "today": today, "week": week, "limit": limit, "admins": len(admins),
        "waitlist": premium.waitlist_summary(exclude=admins),
        "notify": notify.notice_summary(exclude=admins),
    }
    if db_configured():
        stats.update(_collect_from_database(today, week, limit, admins))
    else:
        stats.update(_collect_from_memory(today, week, limit, set(admins)))
    return stats


# Every query leaves out the admins with this condition.
NOT_ADMIN = "user_id <> ALL(%(admins)s::bigint[])"


def _collect_from_database(today: date, week: date, limit: int, admins: List[int]) -> Dict:
    params = {"today": today, "week": week, "limit": limit, "admins": admins}
    with connection() as conn, conn.cursor() as cur:
        active = {}
        for name, start in (("today", today), ("week", week)):
            cur.execute(f"""
                SELECT COUNT(*) FROM (
                    SELECT user_id FROM darsai_daily_activity WHERE day >= %(start)s
                    UNION SELECT user_id FROM darsai_ai_usage WHERE day >= %(start)s
                    UNION SELECT user_id FROM darsai_mastery
                          WHERE updated_at >= (%(start)s::timestamp AT TIME ZONE 'UTC')
                ) AS active
                WHERE {NOT_ADMIN}
            """, dict(params, start=start))
            active[name] = cur.fetchone()[0]
        cur.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT user_id FROM darsai_daily_activity
                UNION SELECT user_id FROM darsai_ai_usage
                UNION SELECT user_id FROM darsai_mastery
                UNION SELECT user_id FROM darsai_student
                UNION SELECT user_id FROM darsai_user_profile
                UNION SELECT user_id FROM darsai_ai_messages
                UNION SELECT user_id FROM darsai_premium_waitlist
                UNION SELECT user_id FROM darsai_first_seen
            ) AS everyone
            WHERE {NOT_ADMIN}
        """, params)
        active["total"] = cur.fetchone()[0]

        cur.execute(f"""
            SELECT source,
                   COUNT(*) FILTER (WHERE first_seen_at >= (%(today)s::timestamp AT TIME ZONE 'UTC')),
                   COUNT(*) FILTER (WHERE first_seen_at >= (%(week)s::timestamp AT TIME ZONE 'UTC')),
                   COUNT(*)
            FROM darsai_first_seen WHERE {NOT_ADMIN}
            GROUP BY source
        """, params)
        sources = {source: (n_today, n_week, n_total) for source, n_today, n_week, n_total in cur.fetchall()}

        cur.execute(f"""
            SELECT COALESCE(SUM(practice_answers) FILTER (WHERE day = %(today)s AND {NOT_ADMIN}), 0),
                   COALESCE(SUM(practice_answers) FILTER (WHERE day >= %(week)s AND {NOT_ADMIN}), 0),
                   MIN(day)
            FROM darsai_daily_activity
        """, params)
        practice_today, practice_week, counting_since = cur.fetchone()
        cur.execute(f"SELECT COALESCE(SUM(correct_count + wrong_count), 0) FROM darsai_mastery WHERE {NOT_ADMIN}", params)
        practice_total = cur.fetchone()[0]

        cur.execute(f"""
            SELECT COALESCE(SUM(count) FILTER (WHERE day = %(today)s), 0),
                   COALESCE(SUM(count) FILTER (WHERE day >= %(week)s), 0),
                   COALESCE(SUM(count), 0),
                   COUNT(*) FILTER (WHERE day = %(today)s AND %(limit)s > 0 AND count >= %(limit)s)
            FROM darsai_ai_usage WHERE {NOT_ADMIN}
        """, params)
        tutor_today, tutor_week, tutor_total, limit_hits = cur.fetchone()

    return {
        "active": active,
        "new": _new_students(sources),
        "practice": {"today": practice_today, "week": practice_week, "total": practice_total},
        "tutor": {"today": tutor_today, "week": tutor_week, "total": tutor_total},
        "limit_hits": limit_hits,
        "counting_since": counting_since,
    }


def _collect_from_memory(today: date, week: date, limit: int, admins: Set[int]) -> Dict:
    """The same numbers from the in-memory fallbacks (local testing without a database)."""
    days = {key: row for key, row in activity._FALLBACK.items() if key[1] not in admins}
    usage = {key: count for key, count in ai._USAGE_FALLBACK.items() if key[0] not in admins}  # only today
    mastery = {key: entry for key, entry in shared.MASTERY_FALLBACK.items() if key[0] not in admins}
    first_seen = {uid: dict(row) for uid, row in activity._FIRST_SEEN.items() if uid not in admins}

    def active_since(start: date) -> int:
        users = {uid for (day, uid) in days if day >= start} | {uid for (uid, day) in usage if day >= start}
        return len(users)

    everyone = (
        {uid for (_, uid) in days} | {uid for (uid, _) in usage} | {uid for (uid, _, _) in mastery}
        | set(student._FALLBACK) | {uid for (_, uid, _) in ai._MEMORY_FALLBACK} | {uid for (uid, _) in premium._FALLBACK}
        | set(first_seen)
    ) - admins
    sources: Dict[Optional[str], Tuple[int, int, int]] = {}
    for row in first_seen.values():
        seen_day = row["at"].date()
        n_today, n_week, n_total = sources.get(row["source"], (0, 0, 0))
        sources[row["source"]] = (n_today + (seen_day >= today), n_week + (seen_day >= week), n_total + 1)
    return {
        "active": {"today": active_since(today), "week": active_since(week), "total": len(everyone)},
        "new": _new_students(sources),
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
        "counting_since": min((day for (day, _) in activity._FALLBACK), default=None),
    }


def _new_students(sources: Dict[Optional[str], Tuple[int, int, int]]) -> Dict:
    """{"today", "week", "total", "sources": [(source, today, week, total)], "no_link": (…)}, links by size."""
    totals = [sum(numbers[i] for numbers in sources.values()) for i in range(3)]
    links = sorted(
        ((source,) + numbers for source, numbers in sources.items() if source is not None),
        key=lambda row: (-row[3], -row[2], -row[1], row[0]),
    )
    return {
        "today": totals[0], "week": totals[1], "total": totals[2],
        "sources": links, "no_link": sources.get(None, (0, 0, 0)),
    }


def _students(count: int) -> str:
    return f"{count:,} student" + ("" if count == 1 else "s")


def format_stats(stats: Dict) -> str:
    def periods(numbers: Dict) -> str:
        return f"Today: {numbers['today']:,} · Last {WEEK_DAYS} days: {numbers['week']:,} · All time: {numbers['total']:,}"

    def three(numbers) -> str:
        return " · ".join(f"{n:,}" for n in numbers)

    new = stats["new"]
    waitlist = stats["waitlist"]
    sources = waitlist["sources"]
    lines = [
        f"📊 {BOT_NAME} stats · {stats['today'].isoformat()} (UTC)",
        "",
        "👥 Active students",
        periods(stats["active"]),
        "",
        "🔗 New students",
        periods(new),
    ]
    if new["sources"]:
        lines.append(f"By start link (today · last {WEEK_DAYS} days · all time):")
        lines += [f"{source}: {three(numbers)}" for source, *numbers in new["sources"][:MAX_SOURCES]]
        rest = new["sources"][MAX_SOURCES:]
        if rest:
            summed = [sum(row[i] for row in rest) for i in (1, 2, 3)]
            lines.append(f"{len(rest):,} more links: {three(summed)}")
        lines.append(f"No link: {three(new['no_link'])}")
    lines += [
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
    lines += ["", f"🔔 Notify me (coming-soon courses): {_students(stats['notify']['students'])}"]
    lines += [
        f"{COURSES[course].emoji} {COURSES[course].name('en')}: {count:,}"
        for course, count in stats["notify"]["courses"].items()
    ]
    since = stats["counting_since"] or stats["today"]
    if since > stats["week"]:
        lines += [
            "",
            f"Counting by day started {since.isoformat()}. Before that, active students only include tutor "
            "and practice use, and practice answers are only in All time.",
        ]
    if stats["admins"]:
        lines += ["", "Admins (ADMIN_USER_IDS) are left out of every number."]
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
    stats = await asyncio.to_thread(collect_stats, activity.utc_today(), ADMIN_USER_IDS)
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
