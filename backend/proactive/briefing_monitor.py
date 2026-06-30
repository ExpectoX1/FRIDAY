"""Scheduled daily briefing — the proactive 'briefing' trigger kind.

"Brief me every morning at 8" registers a recurring daily trigger of this kind;
each time it fires the scheduler speaks a freshly-built briefing (today's
calendar + mail + reminders), so the content is always current — never the
stale snapshot from when the schedule was created.

Mirrors mail_monitor.py: the leaf data composer lives in tools/briefing.py; this
module only adapts it to the scheduler and registers the kind. A briefing is
always worth speaking (the user asked for it), so unlike the web/mail monitors
there's no novelty judgment — the action just returns the briefing text.
"""
from __future__ import annotations

from typing import Optional

from tools.briefing import build_briefing
from proactive.scheduler import register_kind, Trigger


def check_briefing(trigger: Trigger) -> Optional[str]:
    """Scheduler action for kind='briefing'. Builds and returns today's briefing."""
    try:
        return build_briefing()
    except Exception:
        return None


# Recurring briefings roll forward like any daily trigger; they're deliberately
# NOT in the scheduler's startup-replay set — a missed 8am briefing replayed at a
# random later startup time would be stale, so it just waits for tomorrow.
register_kind("briefing", action=check_briefing)
