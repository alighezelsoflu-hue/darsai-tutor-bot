# Load test and baseline

`scripts/load_test.py` sends many simulated students' updates through the real handlers
(`telegram_app.process_update`), with Telegram's API and the AI provider replaced by stand-ins that wait a set
time. Each student: `/start` and the three setup questions, the Math hub, two practice questions answered by
typing (one wrong first), Ask the tutor, Solve, Plot, Progress, Home, ▶️ Continue, 🔔 Notify me and a Premium
pick (20 updates).

```bash
python scripts/load_test.py                                   # 300 students, in-memory storage
python scripts/load_test.py --students 1000 --ramp 30
python scripts/load_test.py --database-url postgresql://postgres@127.0.0.1:55432/darsai_load_test --pool 10
```

With `--database-url` the database's name must contain "test" (its darsai_* tables are dropped first). Other
options: `--ramp` (seconds over which students arrive), `--think` (average seconds between a student's
actions), `--telegram-ms`, `--ai-seconds`. `tests/test_baseline.py` runs it with 4 students so it keeps working.

On Render, memory is in the startup log ("Started in … s: memory … MB (peak … MB) of 512 MB") and at the end
of `/stats` ("🖥 This server: …").

## Baseline, 2026-11-22 (before Phase 1)

Develop at `9a92f5f` plus the step 7 branch. A MacBook (one Python process, so effectively one core), Python
3.11, local PostgreSQL 18. 300 students arriving over 10 s, about 0.5 s between a student's actions, each
Telegram call 60 ms, each AI answer 1.5 s. That is 130–200 updates a second: far more than normal use (for
20,000 students, 2% active at once acting every 10 s would be about 40 updates a second).

| | In memory | PostgreSQL, pool 5 | PostgreSQL, pool 15 |
|---|---|---|---|
| 6,000 updates in | 29–31 s (196–204/s) | 41–46 s (130–145/s) | 42 s (142/s) |
| Errors | 0 | 0 | 0 |
| CPU time per update | ~5 ms | ~10 ms | — |
| Memory, peak | 149 MB | 142 MB | 145 MB |

Handler time per update (median / 95th percentile), and database connections borrowed per update:

| Update | In memory | PostgreSQL, pool 5 | DB calls |
|---|---|---|---|
| /start (setup question 1) | 62 / 73 ms | 295 / 918 ms | 4 |
| setup: first course (Math hub) | 244 / 468 ms | 670 / 1315 ms | 4 |
| practice: new question | 124 / 557 ms | 822 / 1423 ms | 4 |
| practice: typed answer | 182 / 731 ms | 1146 / 1916 ms | 5 |
| tutor: question (AI 1.5 s) | 1857 / 2803 ms | 3797 / 4249 ms | 7 |
| solve: equation | 172 / 695 ms | 985 / 1319 ms | 3 |
| plot: graph (drawing) | 838 / 1364 ms | 1611 / 1999 ms | 3 |
| home | 190 / 875 ms | 1503 / 2075 ms | 5 |
| continue | 158 / 899 ms | 1708 / 2379 ms | 6 |

Other numbers:
- Import of `main`: 0.6–1.0 s. Startup migration check: 0.05–0.12 s (local database).
- Memory after import: 62 MB (peak). `sympy` (Release 2) adds about 42 MB when imported and 48 MB after
  solving, simplifying, differentiating and integrating; a separate solver process would be about 55–70 MB.
- The pool's check of each borrowed connection (`check_connection`, one extra query each time) costs 5–10%.

What it shows:
1. **CPU, not memory, is the first limit.** About 10 ms of CPU per update with PostgreSQL, so one full core
   handles roughly 100–150 updates a second. Render's instances get a fraction of a core (check the plan
   page: Starter is a half), so expect about a third to half of that on Render before updates queue up.
2. **Database calls per update (2–7) matter more than the pool size**: a pool of 15 instead of 5 barely
   helped. Several are repeated reads of the same row in one update (e.g. `darsai_student` for the language
   and again for the level). Fewer calls per update is the cheapest speed-up.
3. **Memory has room**: about 150 MB at peak under this load, so `sympy` fits under 512 MB, also as a
   separate process.
4. Plot drawing is the slowest non-AI action (0.8–1.6 s median under load).

These numbers are from a laptop and are for comparison between versions, not a promise for Render.
