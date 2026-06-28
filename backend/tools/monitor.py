"""Monitor tool — the brain's interface to web watchers.

"FRIDAY, monitor Fabrizio for Barcelona news" -> set_monitor registers a
recurring 'monitor' trigger; the scheduler polls it on its interval and speaks
only when something new and important shows up (see proactive/monitors.py).

Importing this module also registers the 'monitor' trigger kind (via
proactive.monitors), so registry.py importing the tool is enough to wire it up.
"""
from __future__ import annotations

import time

from proactive.scheduler import scheduler, Trigger
from proactive.timeparse import parse_interval
import proactive.monitors  # noqa: F401 — registers the 'monitor' kind on import


def _humanize_interval(seconds: float) -> str:
    if seconds < 3600:
        return f"{int(round(seconds / 60))} minutes"
    if seconds < 86400:
        h = seconds / 3600
        return f"{h:.0f} hour{'s' if h != 1 else ''}"
    return f"{seconds / 86400:.0f} days"


def set_monitor(query: str, interval: str = "") -> dict:
    """Watch the web for a topic and proactively alert the user when something
    new and important appears. `query` is what to watch (a person, team, topic);
    `interval` is how often to check ('every 30 minutes', '1 hour') — defaults to
    every 30 minutes."""
    if not query or not query.strip():
        return {"status": "error", "message": "What should I monitor, Sir?"}

    seconds = parse_interval(interval, default=1800.0)
    scheduler.add(Trigger(
        message=query.strip(),
        fire_at=time.time() + seconds,
        kind="monitor",
        recurrence={"kind": "interval", "seconds": seconds},
        label=query.strip()[:40],
        state={"query": query.strip(), "seen": [], "primed": False, "last_alert": ""},
    ))
    return {"status": "success",
            "message": f"On it, Sir. I'll watch for {query.strip()} every "
                       f"{_humanize_interval(seconds)} and let you know the moment something drops."}
