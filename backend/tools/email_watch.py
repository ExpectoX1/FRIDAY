"""watch_email tool — the brain's interface to the proactive Gmail watcher.

"FRIDAY, tell me when I get an important email" -> watch_email registers a
recurring 'mail_monitor' trigger; the scheduler polls it and speaks when new
matching mail lands (see proactive/mail_monitor.py).

Importing this module also registers the 'mail_monitor' kind (via
proactive.mail_monitor), so registry.py importing the tool wires it up.
"""
from __future__ import annotations

import time

from proactive.scheduler import scheduler, Trigger
from proactive.timeparse import parse_interval
from tools.gmail_tool import _creds, _to_gmail_query
import proactive.mail_monitor  # noqa: F401 — registers the 'mail_monitor' kind


def _humanize_interval(seconds: float) -> str:
    if seconds < 3600:
        return f"{int(round(seconds / 60))} minutes"
    if seconds < 86400:
        h = seconds / 3600
        return f"{h:.0f} hour{'s' if h != 1 else ''}"
    return f"{seconds / 86400:.0f} days"


def watch_email(criteria: str = "", interval: str = "") -> dict:
    """Proactively watch the user's Gmail and alert them when new mail matching
    `criteria` arrives ('important', 'starred', 'from boss@x.com'). `interval` is
    how often to check ('every 10 minutes') — defaults to every 5 minutes."""
    if _creds() is None:
        return {"status": "error",
                "message": "I don't have your Gmail credentials yet, Sir. Add GMAIL_USER "
                           "and GMAIL_APP_PASSWORD to the backend .env first."}

    gmail_query, label = _to_gmail_query(criteria or "important")
    seconds = parse_interval(interval, default=300.0)
    scheduler.add(Trigger(
        message=f"watch email: {label}",
        fire_at=time.time() + seconds,
        kind="mail_monitor",
        recurrence={"kind": "interval", "seconds": seconds},
        label=f"email: {label}"[:40],
        state={"criteria": gmail_query, "label": label, "seen": [], "primed": False},
    ))
    return {"status": "success",
            "message": f"Done, Sir. I'll watch for {label} mail every "
                       f"{_humanize_interval(seconds)} and let you know the moment one lands."}
