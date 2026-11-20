# DarsAI MVP and Scaling Roadmap

## Product identity
DarsAI is not a generic Telegram ChatGPT clone. It is a specialized AI teaching assistant that helps students learn step by step, practice, check answers, and build mastery.

Slogan: **DarsAI — Not just answers. Real learning.**

## Phase 1 — Core MVP
- Telegram bot with FastAPI webhook
- `/start` menu
- AI tutor module
- Math module
- Plot module
- Basic practice and answer checking
- Per-user AI memory
- Basic progress tracking

## Phase 2 — Learning structure
Math is organized by level:
- Middle School
- High School
- Pre-College
- University

Each level can contain topic modules with lessons, practice templates, common mistakes, and examples.

## Phase 3 — AI tutor memory
Memory key:
`chat_id + user_id + topic`

This lets each student continue their own learning thread, even inside Telegram groups.

## Phase 4 — Progress tracking
Track:
- correct answers
- wrong answers
- mastery by topic
- recommended next topic

## Phase 5 — Subscription system
MVP starts free. Later:
- Free: limited AI messages and basic lessons
- Premium: more AI tutor messages, personalized study plan, progress insights
- School: teacher dashboard and class analytics

## Phase 6 — Knowledge graph
Future knowledge graph nodes:
- topics
- prerequisites
- learning objectives
- common mistakes
- practice templates
- related concepts

Example:
Quadratics → requires factoring → leads to functions → common mistake: sign errors.

## Phase 7 — Scale to 1M users
Start with Render + Neon + hosted LLM API. Later migrate to:
- stronger cloud server / Kubernetes
- managed PostgreSQL cluster
- Redis for rate limits and sessions
- queue workers for AI jobs
- vector database and knowledge graph
- multi-provider LLM fallback
- monitoring and analytics

## Current MVP files
- `main.py`
- `config.py`
- `modules/ai.py`
- `modules/db.py` (shared PostgreSQL connection pool)
- `modules/common.py` (languages, long-message splitting)
- `modules/math/math.py`
- `modules/math/plot.py`
- `modules/math/shared.py`
- `modules/math/prompts.py`
- level submodules under `modules/math/`
