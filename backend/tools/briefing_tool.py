"""daily_briefing tool — the brain's interface to the briefing.

Two modes, one tool:
  • No time  -> build and speak the briefing RIGHT NOW ("good morning",
    "brief me", "what's my day look like").
  • A time   -> schedule a recurring (or one-shot) 'briefing' trigger so the
    scheduler delivers it hands-free ("brief me every morning at 8").

Importing this module also registers the 'briefing' kind (via
proactive.briefing_monitor), so registry.py importing the tool wires up the
scheduled path at startup — needed so a briefing trigger persisted in
reminders.json fires correctly after a restart even if nobody re-schedules it.
"""
from __future__ import annotations

from tools.briefing import build_briefing
from proactive.scheduler import scheduler, Trigger
from proactive.timeparse import parse_when
import proactive.briefing_monitor  # noqa: F401 — registers the 'briefing' kind


def daily_briefing(when: str = ""):
    """Give the user their daily briefing (today's calendar, unread mail, and
    reminders). With no `when`, briefs now and returns the spoken text. With a
    `when` ('every morning at 8', 'every day at 7:30am'), schedules a recurring
    briefing and returns a confirmation."""
    if not (when and when.strip()):
        return build_briefing()

    parsed = parse_when(when)
    if parsed is None:
        return {"status": "error",
                "message": "When should I brief you, Sir? Try 'every morning at 8'."}

    # Re-scheduling replaces any existing briefing rather than stacking duplicates.
    for t in list(scheduler.list_pending()):
        if t.kind == "briefing":
            scheduler.cancel(t.id)

    scheduler.add(Trigger(
        message="daily briefing",
        fire_at=parsed.fire_at,
        kind="briefing",
        recurrence=parsed.recurrence,
        label="daily briefing",
    ))
    cadence = parsed.pretty if parsed.recurrence else f"once, {parsed.pretty}"
    return {"status": "success",
            "message": f"Done, Sir. I'll brief you {cadence}."}
