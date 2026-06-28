"""Reminder/timer tools — the brain's interface to the proactive scheduler.

These are thin: they parse the human time spec, register a Trigger with the
shared scheduler, and return a spoken confirmation. The scheduler thread does
the actual firing (see proactive/scheduler.py).
"""
from __future__ import annotations

from datetime import datetime

from proactive.scheduler import scheduler, Trigger
from proactive.timeparse import parse_when


def _spoken_time(fire_at: float) -> str:
    dt = datetime.fromtimestamp(fire_at)
    if dt.date() == datetime.now().date():
        return dt.strftime("%I:%M %p").lstrip("0")
    return dt.strftime("%A at %I:%M %p").replace(" 0", " ")


def set_reminder(message: str, when: str) -> dict:
    """Schedule a reminder. `message` is what to remind about; `when` is a time
    spec like 'in 10 minutes', 'at 5:30pm', 'tomorrow at 9am', 'every day at 8'."""
    if not message or not message.strip():
        return {"status": "error", "message": "What should I remind you about, Sir?"}
    parsed = parse_when(when)
    if parsed is None:
        return {"status": "error",
                "message": f"I couldn't work out when '{when}' is, Sir. Try 'in 10 minutes' or 'at 5pm'."}

    scheduler.add(Trigger(
        message=message.strip(),
        fire_at=parsed.fire_at,
        kind="reminder",
        recurrence=parsed.recurrence,
        label=message.strip()[:40],
    ))

    if parsed.recurrence:
        return {"status": "success",
                "message": f"I'll remind you to {message.strip()} {parsed.pretty}, Sir."}
    return {"status": "success",
            "message": f"I'll remind you to {message.strip()} {parsed.pretty}, Sir."}


def set_timer(duration: str, label: str = "") -> dict:
    """Set a countdown timer. `duration` is like '5 minutes' or '90 seconds'."""
    parsed = parse_when(duration)
    if parsed is None or parsed.recurrence is not None:
        return {"status": "error",
                "message": f"I couldn't set a timer for '{duration}', Sir. Try '5 minutes'."}

    scheduler.add(Trigger(
        message=label.strip(),
        fire_at=parsed.fire_at,
        kind="timer",
        label=label.strip() or "timer",
    ))
    suffix = f" for {label.strip()}" if label.strip() else ""
    return {"status": "success", "message": f"Timer set{suffix} {parsed.pretty}, Sir."}


def list_reminders() -> dict:
    """List all pending reminders and timers."""
    pending = scheduler.list_pending()
    if not pending:
        return {"status": "success", "message": "You have no reminders or timers set, Sir."}
    lines = []
    for i, t in enumerate(pending, 1):
        what = t.message or ("timer" if t.kind == "timer" else "(unnamed)")
        recur = " (daily)" if (t.recurrence or {}).get("kind") == "daily" else ""
        lines.append(f"{i}. {what} — {_spoken_time(t.fire_at)}{recur}")
    return {"status": "success", "message": "Here's what you have set, Sir: " + "; ".join(lines) + "."}


def cancel_reminder(which: str = "") -> dict:
    """Cancel a reminder or timer by name, number (from list_reminders), or — if
    only one is set — leave `which` empty."""
    removed = scheduler.cancel(which)
    if removed is None:
        return {"status": "error",
                "message": f"I couldn't find a reminder matching '{which}', Sir."}
    what = removed.message or removed.kind
    return {"status": "success", "message": f"Cancelled {what}, Sir."}
