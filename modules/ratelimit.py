"""The per-student speed limit (Phase 1 step 9): how many things a student may do in a short time.

Two budgets per student, over the same RATE_LIMIT_WINDOW_SECONDS (10):
- ACTIONS, RATE_LIMIT_ACTIONS (20): what a student does in the chat (button presses, messages, and in groups
  commands and replies; ui/limit.py) and the Mini App's changes (webapp.api_student("write")).
- READS, RATE_LIMIT_API_READS (60): the Mini App's page loads and its load-time ping (webapp.api_student("read")),
  apart so that switching the app's tabs quickly never blocks the chat's buttons.

A sliding window: each student's times of their allowed actions in the last window. A refused action doesn't
count, so a student who keeps going gets back in as soon as their oldest action is older than the window. Admins
(ADMIN_USER_IDS) have no limit.

Per process and in memory: user ids and times for a few seconds, never stored (docs/data-inventory.md). With
several instances each has its own counts, so a student could do that many times as much; a shared limit would
need PostgreSQL or Redis. Delete my data forgets a student here too (ui/privacy.forget_in_process).

A lock guards the counts, because run_local.py serves the Mini App from another thread. No Telegram or web
objects here.
"""

import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Optional, Tuple

import config

# Students idle for a whole window are dropped from memory at most this often.
SWEEP_SECONDS = 60


class SpeedLimit:
    """One budget: at most getattr(config, setting) allowed actions per student in any RATE_LIMIT_WINDOW_SECONDS."""

    def __init__(self, setting: str, clock: Callable[[], float] = time.monotonic):
        self.setting = setting
        self.clock = clock
        self.refused = 0  # since the process started, no user ids (the load test reports it)
        self._times: Dict[int, Deque[float]] = {}
        self._warned: Dict[int, float] = {}
        # Something the caller keeps about a student while they are being refused (the chat: their language), so
        # more refusals cost no database read. Dropped by their next allowed action.
        self._notes: Dict[int, Tuple[float, str]] = {}
        self._lock = threading.Lock()
        self._next_sweep = 0.0

    @property
    def limit(self) -> int:
        return getattr(config, self.setting)

    def allow(self, user_id: int) -> bool:
        """Counts the action and returns True, or returns False (and doesn't count it) over the limit."""
        if user_id in config.ADMIN_USER_IDS:
            return True
        now, window = self.clock(), config.RATE_LIMIT_WINDOW_SECONDS
        with self._lock:
            if now >= self._next_sweep:
                self._sweep(now, window)
            times = self._times.get(user_id)
            if times is None:
                times = self._times[user_id] = deque()
            while times and now - times[0] >= window:
                times.popleft()
            if len(times) >= self.limit:
                self.refused += 1
                return False
            times.append(now)
            self._notes.pop(user_id, None)
            return True

    def note(self, user_id: int) -> Optional[str]:
        """What set_note kept for a student being refused, if it is from the last window."""
        now, window = self.clock(), config.RATE_LIMIT_WINDOW_SECONDS
        with self._lock:
            kept = self._notes.get(user_id)
            return kept[1] if kept is not None and now - kept[0] < window else None

    def set_note(self, user_id: int, value: str) -> None:
        with self._lock:
            self._notes[user_id] = (self.clock(), value)

    def first_refusal(self, user_id: int) -> bool:
        """After a refusal: True once per window, so a typed message gets one warning and the rest are skipped."""
        now, window = self.clock(), config.RATE_LIMIT_WINDOW_SECONDS
        with self._lock:
            warned = self._warned.get(user_id)
            if warned is not None and now - warned < window:
                return False
            self._warned[user_id] = now
            return True

    def retry_after(self, user_id: int) -> float:
        """Seconds until the student may act again (0: now)."""
        now, window = self.clock(), config.RATE_LIMIT_WINDOW_SECONDS
        with self._lock:
            times = self._times.get(user_id)
            if not times or len(times) < self.limit:
                return 0.0
            return max(0.0, times[0] + window - now)

    def forget(self, user_id: int) -> None:
        with self._lock:
            self._times.pop(user_id, None)
            self._warned.pop(user_id, None)
            self._notes.pop(user_id, None)

    def clear(self) -> None:
        with self._lock:
            self._times.clear()
            self._warned.clear()
            self._notes.clear()
            self._next_sweep = 0.0
            self.refused = 0

    def students(self) -> int:
        """How many students this budget holds times for (tests)."""
        with self._lock:
            return len(self._times)

    def _sweep(self, now: float, window: float) -> None:
        """Holding the lock: drop the students with nothing in the last window."""
        for user_id in [u for u, times in self._times.items() if not times or now - times[-1] >= window]:
            del self._times[user_id]
        for user_id in [u for u, warned in self._warned.items() if now - warned >= window]:
            del self._warned[user_id]
        for user_id in [u for u, (noted, _) in self._notes.items() if now - noted >= window]:
            del self._notes[user_id]
        self._next_sweep = now + SWEEP_SECONDS


ACTIONS = SpeedLimit("RATE_LIMIT_ACTIONS")
READS = SpeedLimit("RATE_LIMIT_API_READS")
BUDGETS = (ACTIONS, READS)


def forget(user_id: int) -> None:
    """Delete my data: the student's times in every budget."""
    for budget in BUDGETS:
        budget.forget(user_id)


def clear() -> None:
    """Tests and the load test: start from nothing."""
    for budget in BUDGETS:
        budget.clear()
