"""watch_notifications tool — turn the proactive message/notification watcher
on or off.

When on, the scheduler polls macOS Notification Center and FRIDAY announces new
messages from the watched sources (WhatsApp, Instagram, …) — safe and
app-agnostic (see proactive/notification_monitor.py). Needs Full Disk Access for
the process running FRIDAY.
"""
from __future__ import annotations

import time

from proactive.scheduler import scheduler, Trigger
from tools.notifications_tool import available, _parse_sources
import proactive.notification_monitor  # noqa: F401 — registers the kind

_POLL_SECONDS = 10.0  # notifications aren't urgent-to-the-second; 10s feels live


def watch_notifications(sources: str = "", mode: str = "on") -> dict:
    """Start ('on') / stop ('off') watching macOS notifications for messages.
    `sources` is what to watch ('whatsapp instagram'); empty = messaging
    defaults."""
    if (mode or "").strip().lower() in ("off", "stop", "disable", "no", "false"):
        removed = scheduler.cancel("notifications")
        return {"status": "success",
                "message": "Stopped watching your notifications, Sir." if removed
                           else "I wasn't watching your notifications, Sir."}

    if not available():
        return {"status": "error",
                "message": "I can't see your notifications yet, Sir — grant Full Disk "
                           "Access to the terminal you run me from, then try again."}

    src = _parse_sources(sources)
    scheduler.cancel("notifications")  # don't stack duplicate watchers
    scheduler.add(Trigger(
        message="notification watch",
        fire_at=time.time() + _POLL_SECONDS,
        kind="notification_monitor",
        recurrence={"kind": "interval", "seconds": _POLL_SECONDS},
        label="notifications",
        state={"sources": src, "last_rec_id": 0, "primed": False},
    ))
    return {"status": "success",
            "message": f"On it, Sir. I'll watch for {', '.join(src[:3])} messages and "
                       "let you know the moment one lands."}
