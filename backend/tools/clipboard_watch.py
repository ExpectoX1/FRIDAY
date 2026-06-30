"""watch_clipboard tool — turn the proactive clipboard companion on/off.

When on, the scheduler polls the clipboard every few seconds and FRIDAY offers
help when you copy something useful (see proactive/clipboard_monitor.py).
Off by default because watching the clipboard is sensitive — the user enables it
explicitly ("keep an eye on my clipboard").
"""
from __future__ import annotations

import time

from proactive.scheduler import scheduler, Trigger
import proactive.clipboard_monitor  # noqa: F401 — registers the 'clipboard_monitor' kind

_POLL_SECONDS = 3.0  # clipboard changes are user-driven; a few seconds feels live


def watch_clipboard(mode: str = "on") -> dict:
    """Enable ('on') or disable ('off') the proactive clipboard companion."""
    if (mode or "").strip().lower() in ("off", "stop", "disable", "no", "false"):
        removed = scheduler.cancel("clipboard")
        return {"status": "success",
                "message": "Stopped watching your clipboard, Sir." if removed
                           else "I wasn't watching your clipboard, Sir."}

    scheduler.cancel("clipboard")  # avoid stacking duplicate watchers
    scheduler.add(Trigger(
        message="clipboard watch",
        fire_at=time.time() + _POLL_SECONDS,
        kind="clipboard_monitor",
        recurrence={"kind": "interval", "seconds": _POLL_SECONDS},
        label="clipboard",
        state={"last_hash": "", "primed": False},
    ))
    return {"status": "success",
            "message": "On it, Sir. I'll keep an eye on your clipboard and chime in when I can help."}
