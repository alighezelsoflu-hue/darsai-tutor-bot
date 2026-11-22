# What DarsAI stores about students

Every place the bot keeps data about a student, why, and for how long. Keep it up to date when a table, a field
or a service that receives data is added: the privacy policy (`privacy.*` in `modules/i18n/en.py` and `fa.py`,
shown by `/privacy`) is written from this list.

🗑 Delete my data (`/deletemydata`, ⚙️ Settings → 🔒 Privacy) deletes the student's rows from **every**
`darsai_*` table with a `user_id` column, found when it runs (`modules/privacy.py`), in one transaction,
except today's tutor-message count (see `darsai_ai_usage` below). A new
table with a `user_id` column is covered automatically. A table that holds personal data **without** a
`user_id` column would not be: give every such table a `user_id` column.

This is a description of what the code does, not legal advice. Many students are minors and the bot is run
from Europe, so the GDPR may apply. Please check it with someone qualified.

## In the database (PostgreSQL on Neon, Frankfurt)

| Table | What | Why | Kept |
|---|---|---|---|
| `darsai_student` | Telegram user id, interface language, level, `setup_done`, `keyboard_version`, created/updated time | Settings that follow the student into every chat | Until deleted |
| `darsai_user_profile` | Chat id, user id, level, language (old, per chat) | Read only as a fallback for levels saved before `darsai_student` existed; never written | Until deleted |
| `darsai_mastery` | User id, level, topic, mastery (0–1), correct and wrong counts, last practice time | Progress, the next difficulty, ▶️ Continue, Suggested next | Until deleted |
| `darsai_active_question` | Chat id, user id, the current practice question (generated numbers, the answer, the message ids showing it) | Checking the typed answer; one per chat | Until answered or replaced (typed text stops counting after 24 hours) |
| `darsai_input_mode` | Chat id, user id, the open tool (tutor, solve, plot), its message ids, the last equation solved (as typed) | Sending typed text to the right tool; 🧑‍🏫 Explain step by step | Until the student leaves the tool (it stops counting after 24 hours) |
| `darsai_ai_messages` | Chat id, user id, topic, role, the text of each tutor question and answer, time | The tutor remembers the conversation (the last `AI_MAX_HISTORY_MESSAGES` per topic are sent) | Until 🧹 Clear tutor memory, `/newchat` or deletion. Phase 1 step 11 adds: newest 16 per conversation, at most 90 days |
| `darsai_ai_usage` | User id, UTC day, tutor messages that day | The daily limit; `/stats` | Until deleted. Delete my data keeps **today's** row until the day ends, so deleting can't reset the daily limit (otherwise a student could delete again and again for unlimited tutor messages, at the bot owner's cost). After that day it is removed at the next startup or Delete my data (`privacy.drop_kept_usage`) |
| `darsai_daily_activity` | UTC day, user id, practice answers that day | `/stats` (active students, practice answers) | Until deleted |
| `darsai_first_seen` | User id, start-link source (if any), first time seen | `/stats` (new students per start link) | Until deleted |
| `darsai_premium_waitlist` | User id, Premium pick, where it was picked, interface language, time | The waitlist; announcing Premium in the student's language | Until the pick is removed or deleted |
| `darsai_course_notify` | User id, coming-soon course, interface language, time | 🔔 Notify me; announcing the course in the student's language | Until deleted (rows for removed courses, e.g. Astrology, stay until then) |
| `darsai_math_progress` | Chat id, user id, level, topic, counts (old, production only) | Never read or written since mastery existed; copied into `darsai_mastery` once | Until deleted |
| `darsai_schema_version` | Applied migrations | No personal data | — |

Not stored anywhere: names, usernames, phone numbers, photos, Telegram profile data. In groups the bot shows
"👤 first name" on a student's menu, read from the update and not saved.

## Outside the database

- **In memory (per process):** user ids the activity tracker has seen today (`stats._seen`) and students who
  have the current bottom keyboard (`setup._current`). Cleared by Delete my data and at every restart.
- **The AI provider** (`AI_PROVIDER`, Groq by default, a US company) receives each tutor question with the
  recent conversation on that topic and the system prompt. No user id, chat id or name is sent.
- **Render** (server, Frankfurt) keeps the console log for a limited time. It can contain Telegram user ids
  (e.g. "Ignored /stats from user id …", "Deleted the data of user id …") and error messages; secrets are
  scrubbed (`modules/alerts.py`), and update contents are never logged.
- **Error alerts** go to the admins (`ADMIN_USER_IDS`) on Telegram: the error, where it happened and the log
  message, cut to 300 characters. Never the update or what a student sent, though an exception message can
  contain a few characters a student typed (e.g. "Unknown name: abc").
- **Sentry**, only when `SENTRY_DSN` is set: the same as the alerts, with user info, request data and local
  variables switched off.
- **Telegram** keeps the chat messages themselves. They are separate from the bot's database, and the student
  deletes them in Telegram.
