"""What a student's next typed message in a chat is for: a question for the tutor, an equation, a function.

A student has at most one input mode per chat. It is a JSON dict with at least "id" and "mode", stored in
darsai_input_mode. Practice answers are separate (darsai_active_question); while an input mode is set,
typed text goes to it first.

All functions are blocking. Call them with asyncio.to_thread.
"""

import json
import threading
from typing import Dict, Optional, Tuple

from modules.db import connection, db_configured

# In-memory fallback, used only when DATABASE_URL is not set. Stored as JSON copies, like the JSONB column.
_FALLBACK: Dict[Tuple[int, int], Dict] = {}
_LOCK = threading.Lock()


def init_input_db() -> None:
    if not db_configured():
        return
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS darsai_input_mode (
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                state JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY(chat_id, user_id)
            );
        """)


def set_input_mode(chat_id: int, user_id: int, state: Dict) -> None:
    """Start a new input mode, replacing any other."""
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO darsai_input_mode (chat_id, user_id, state) VALUES (%s, %s, %s::jsonb)
                ON CONFLICT (chat_id, user_id) DO UPDATE SET state=EXCLUDED.state, updated_at=NOW();
            """, (chat_id, user_id, json.dumps(state)))
        return
    with _LOCK:
        _FALLBACK[(chat_id, user_id)] = json.loads(json.dumps(state))


def update_input_mode(chat_id: int, user_id: int, state: Dict) -> bool:
    """Save changes, but only while the same input mode (same id) is still set.

    Returns False when the student left it in the meantime, so a mode they left never comes back.
    """
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE darsai_input_mode SET state=%s::jsonb, updated_at=NOW()
                WHERE chat_id=%s AND user_id=%s AND state->>'id'=%s
            """, (json.dumps(state), chat_id, user_id, str(state["id"])))
            return cur.rowcount > 0
    with _LOCK:
        stored = _FALLBACK.get((chat_id, user_id))
        if stored is None or stored.get("id") != state["id"]:
            return False
        _FALLBACK[(chat_id, user_id)] = json.loads(json.dumps(state))
        return True


def get_input_mode(chat_id: int, user_id: int) -> Optional[Dict]:
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT state FROM darsai_input_mode WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
            row = cur.fetchone()
        if not row:
            return None
        return json.loads(row[0]) if isinstance(row[0], str) else row[0]
    with _LOCK:
        state = _FALLBACK.get((chat_id, user_id))
        return json.loads(json.dumps(state)) if state else None


def clear_input_mode(chat_id: int, user_id: int) -> None:
    if db_configured():
        with connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM darsai_input_mode WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
        return
    with _LOCK:
        _FALLBACK.pop((chat_id, user_id), None)
