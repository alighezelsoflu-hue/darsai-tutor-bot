# Operations checklist (Phase 0, step 6)

Things only the bot's owner can do, in the Neon, Render, GitHub and Telegram accounts. Tick them off and
note the date. Nothing here changes code.

## Region (done 2026-11-22)

- [x] Neon (database) and Render (server) are in the same region: both Frankfurt (Neon `aws-eu-central-1`).
  Every database call crosses between them, so a different region would add delay to every button press.

## Backups and restore (Neon)

On Neon's Free plan, the restore window is **6 hours** (Launch: up to 7 days, Scale: up to 30), and the Free
plan has **1 manual snapshot**. Anything older than the window can only come back from a snapshot.

- [ ] **Try a restore once, into a branch** (this doesn't touch production):
  1. Neon console → your project → **Branches** → **Create branch**.
  2. Parent: the production branch. Choose **a past point in time** (e.g. one hour ago).
  3. Open the new branch's **SQL Editor** and check the data is there, e.g.
     `SELECT COUNT(*) FROM darsai_student;` and `SELECT MAX(version) FROM darsai_schema_version;`
  4. Delete the test branch afterwards. It holds a copy of students' data.
- [ ] **Before each release that changes the database** (a new migration in `modules/migrations.py`), take
  the manual snapshot in Neon, or merge within the 6-hour window when you can watch it. A bad migration can then
  be undone by restoring.
- [ ] Know the undo: a **restore** overwrites the branch with its past state, and Neon keeps the state from
  before the restore in a backup branch, so a restore can itself be undone.
- [ ] Optional: once in a while, a `pg_dump` export kept somewhere safe. It contains students' data (many are
  minors): keep it encrypted and delete old ones.

## Security settings

- [x] **Turn off Neon's Data API** on the production project (done 2026-11-22). The bot doesn't use it: it
  connects directly with `DATABASE_URL`. An unused way into the database should be off. Keep it off, and
  turn off Neon Auth too if nothing else uses it.
- [ ] **Two-factor authentication** on every account that can reach the bot or its data: GitHub, Render, Neon,
  Groq, Sentry (if used) and the Telegram account that owns the bot in @BotFather.
- [ ] Secrets live only in Render's Environment settings (and `.env.local` for the test bot), never in the
  repository or a chat. If one leaks:
  - the bot token: @BotFather → `/revoke`, then update `TELEGRAM_BOT_TOKEN` on Render;
  - the database password: reset it in Neon, then update `DATABASE_URL` on Render;
  - an AI key: delete it in the provider's console, then update it on Render.
- [ ] Render → the service → Settings → **Health Check Path**: `/health`. Render then restarts the service if it
  stops answering.

## Before marketing (Phase 1)

- [ ] Render **Starter** plan (the free plan sleeps after about 15 minutes and shares 750 hours a month with
  every free service). After that, the staging bot of step 5.
- [ ] Groq's paid tier: the free tier is about 1,000 requests a day and 8,000 tokens a minute for all students
  together, which is 2–3 tutor answers a minute.
- [ ] Optional: an OpenRouter key for the backup AI provider (Phase 1, step 8).
- [ ] The GDPR question for someone qualified (many students are minors, the bot is run from Europe, tutor
  questions go to a US company): see `docs/data-inventory.md`.
