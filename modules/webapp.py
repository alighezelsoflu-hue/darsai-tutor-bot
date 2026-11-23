"""The Mini App's web routes, in the same FastAPI service as the webhook (main.py includes the router).

    GET  /app                 the page (webapp/index.html, with the app.* texts of both languages filled in)
    GET  /app/app.js, app.css its script and styles
    GET  /api/me/progress     the student's progress, in their language (Telegram launch data required)
    POST /api/miniapp/ping    the page's load timings (Telegram launch data required)

Every /api route takes the student from Telegram's signed launch data only (miniapp.check_init_data), sent as
"Authorization: tma <initData>", and answers 401 without it. The page loads nothing from other hosts (many may
be blocked in Iran): no fonts, no CDN, no telegram.org script. The headers allow only this server
(Content-Security-Policy), and only Telegram's web version may embed the page.
"""

import asyncio
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import config
from modules.i18n import STRINGS, UI_LANGUAGES, detect_language, is_rtl, level_label, local_digits, t
from modules.math.shared import get_mastery, get_user_level
from modules.math.topics import LEVEL_ORDER, topics_for_level
from modules.miniapp import check_init_data, record_open
from modules.student import get_student

router = APIRouter()

WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"
MAX_PING_BYTES = 4096
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'self' https://web.telegram.org"
)
HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-cache",
}


# ------------------------------------------------------------
# The page
# ------------------------------------------------------------

@lru_cache(maxsize=1)
def page_html() -> str:
    """index.html with the page's texts in both languages (a JSON data block: not run, so the CSP allows it)."""
    texts = {lang: {key: text for key, text in STRINGS[lang].items() if key.startswith("app.")} for lang in UI_LANGUAGES}
    data = json.dumps(texts, ensure_ascii=False).replace("</", "<\\/")
    return (WEBAPP_DIR / "index.html").read_text(encoding="utf-8").replace("__TEXTS__", data)


@router.get("/app")
async def app_page() -> HTMLResponse:
    return HTMLResponse(page_html(), headers=HEADERS)


@router.get("/app/app.js")
async def app_script() -> FileResponse:
    return FileResponse(WEBAPP_DIR / "app.js", media_type="text/javascript; charset=utf-8", headers=HEADERS)


@router.get("/app/app.css")
async def app_styles() -> FileResponse:
    return FileResponse(WEBAPP_DIR / "app.css", media_type="text/css; charset=utf-8", headers=HEADERS)


# ------------------------------------------------------------
# Who is calling
# ------------------------------------------------------------

def caller(request: Request) -> Dict:
    """The student, from Telegram's signed launch data in the Authorization header, or 401."""
    header = request.headers.get("authorization", "")
    scheme, _, init_data = header.partition(" ")
    student = None
    if scheme.lower() == "tma":
        student = check_init_data(init_data.strip(), config.TOKEN or "", config.MINIAPP_AUTH_MAX_AGE_SECONDS)
    if student is None:
        raise HTTPException(status_code=401, detail="Open the app from Telegram.")
    return student


def language_of(user_id: int, telegram_language: Optional[str]) -> str:
    """Blocking. The language the student chose in the bot, else a guess from Telegram's language code."""
    saved = get_student(user_id)["language"]
    return saved if saved in UI_LANGUAGES else detect_language(telegram_language)


# ------------------------------------------------------------
# /api/me/progress
# ------------------------------------------------------------

def _topic_name(lang: str, topic: str) -> str:
    try:
        return t(lang, f"topic.{topic}")
    except KeyError:
        return topic


def progress_payload(user_id: int, telegram_language: Optional[str]) -> Dict:
    """Blocking. Everything the Progress page shows, as finished text in the student's language."""
    lang = language_of(user_id, telegram_language)
    level = get_user_level(user_id, user_id)
    mastery = get_mastery(user_id)
    sections: List[Dict] = []
    for section_level in LEVEL_ORDER:
        topics = []
        for topic in topics_for_level(section_level):
            entry = mastery.get((section_level, topic))
            if entry and entry["correct"] + entry["wrong"]:
                share = int(round(entry["mastery"] * 100))
                topics.append({
                    "name": _topic_name(lang, topic),
                    "percent": share,
                    "detail": t(lang, "app.topic_detail", percent=local_digits(lang, share),
                                correct=local_digits(lang, entry["correct"]), wrong=local_digits(lang, entry["wrong"])),
                })
            elif section_level == level:
                topics.append({"name": _topic_name(lang, topic), "percent": 0, "detail": t(lang, "app.not_started")})
        if topics:
            sections.append({"level": "🎓 " + level_label(lang, section_level), "topics": topics})
    practised = any(entry["correct"] + entry["wrong"] for entry in mastery.values())
    suggested = min(topics_for_level(level), key=lambda topic: mastery.get((level, topic), {}).get("mastery", 0.0))
    return {
        "lang": lang,
        "dir": "rtl" if is_rtl(lang) else "ltr",
        "title": t(lang, "progress.title"),
        "empty": None if practised else t(lang, "progress.empty"),
        "sections": sections,
        "suggest": t(lang, "progress.suggest", topic=_topic_name(lang, suggested)),
    }


@router.get("/api/me/progress")
async def my_progress(request: Request) -> JSONResponse:
    student = caller(request)
    payload = await asyncio.to_thread(progress_payload, student["user_id"], student["language_code"])
    return JSONResponse(payload, headers=HEADERS)


# ------------------------------------------------------------
# /api/miniapp/ping
# ------------------------------------------------------------

@router.post("/api/miniapp/ping")
async def ping(request: Request) -> JSONResponse:
    student = caller(request)
    body = await request.body()
    if len(body) > MAX_PING_BYTES:
        raise HTTPException(status_code=413, detail="Too large.")
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Not JSON.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Not an object.")
    await asyncio.to_thread(record_open, student["user_id"], payload)
    return JSONResponse({"ok": True}, headers=HEADERS)
