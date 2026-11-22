"""How much memory the bot uses, and how long it has been running: for the startup log line on Render and the
last line of /stats (Render's free and Starter plans have 512 MB).

No Telegram imports.
"""

import resource
import sys
import time
from typing import Optional, Tuple

# Set when main.py is imported, i.e. about when the server process starts.
STARTED = time.monotonic()
RENDER_MEMORY_MB = 512


def memory_mb() -> Tuple[Optional[float], float]:
    """(memory in use now, or None where it can't be read; the most used so far), in MB.

    On Linux (Render) both come from /proc/self/status (VmRSS, VmHWM). Elsewhere only the peak is known.
    """
    current = peak = None
    try:
        with open("/proc/self/status") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    current = int(line.split()[1]) / 1024
                elif line.startswith("VmHWM:"):
                    peak = int(line.split()[1]) / 1024
    except OSError:
        pass
    if peak is None:
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Bytes on macOS, kilobytes on Linux.
        peak = maxrss / (1024 * 1024) if sys.platform == "darwin" else maxrss / 1024
    return current, peak


def uptime_seconds() -> float:
    return time.monotonic() - STARTED


def describe() -> str:
    """E.g. "memory 142 MB (peak 160 MB) of 512 MB, up 3 h 05 min" (English: admins and logs only)."""
    current, peak = memory_mb()
    used = f"{current:.0f} MB (peak {peak:.0f} MB)" if current is not None else f"peak {peak:.0f} MB"
    minutes = int(uptime_seconds() // 60)
    up = f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"
    return f"memory {used} of {RENDER_MEMORY_MB} MB, up {up}"
