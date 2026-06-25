# DarsAI MVP

A scalable Telegram AI tutor MVP focused on math learning.

## Run on Render
Start command:

```bash
uvicorn main:api --host 0.0.0.0 --port $PORT
```

## Required environment variables

```text
TELEGRAM_BOT_TOKEN=...
WEBHOOK_URL=https://your-render-service.onrender.com
SECRET_PATH=darsai-webhook
AI_PROVIDER=groq
GROQ_API_KEY=...
AI_MODEL=llama-3.1-8b-instant
DATABASE_URL=postgresql://... optional but recommended
AI_MEMORY_ENABLED=true
```

## Test locally

```powershell
$env:TELEGRAM_BOT_TOKEN="123456:TEST_TOKEN"
$env:WEBHOOK_URL="https://example.com"
$env:SECRET_PATH="test-webhook"
python -m py_compile main.py modules/ai.py modules/math/math.py modules/math/plot.py
python -c "import main; print('main OK')"
```

## Core commands

```text
/start
/math
/mathhelp
/level high_school
/lesson high_school quadratics
/math_tutor fa high_school quadratics explain the quadratic formula
/solve 2x + 5 = 17
/practice high_school algebra
/check 5
/plot y=x^2 range -5 5
/progress
/aihelp
/chat explain how to study algebra
```
