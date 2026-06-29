"""Read-only macOS Calendar access — the first brick of the daily-driver layer.

Uses EventKit (PyObjC) rather than AppleScript: the Calendar app's AppleScript
interface is slow and flaky, while EventKit reads the same on-device store
directly and fast. Read-only by design for now — creating/editing events comes
later and must route through the agent's confirmation gate.

First use requires Calendar access for the process running FRIDAY (Terminal /
the app bundle). The OS prompts once; if denied, grant it under
System Settings → Privacy & Security → Calendars. get_calendar() degrades to a
clear spoken message in that case rather than failing silently.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import EventKit as _EK
from Foundation import NSDate, NSRunLoop

_ENTITY_EVENT = _EK.EKEntityTypeEvent
_FULL_ACCESS = getattr(_EK, "EKAuthorizationStatusFullAccess", 3)

def _new_store():
    # Always a fresh store: an EKEventStore created BEFORE access is granted can
    # keep returning zero events even after the grant, so we never cache one
    # across the authorization boundary.
    return _EK.EKEventStore.alloc().init()


def _request_access(store) -> bool:
    """Prompt for (or confirm) Calendar access, blocking briefly on the EventKit
    completion handler via a run-loop spin. Returns True if access is granted."""
    result = {"granted": None}

    def _handler(granted, _err):
        result["granted"] = bool(granted)

    # macOS 14+ uses requestFullAccess…; fall back to the older API on <14.
    if hasattr(store, "requestFullAccessToEventsWithCompletion_"):
        store.requestFullAccessToEventsWithCompletion_(_handler)
    else:
        store.requestAccessToEntityType_completion_(_ENTITY_EVENT, _handler)

    run_loop = NSRunLoop.currentRunLoop()
    deadline = time.time() + 10
    while result["granted"] is None and time.time() < deadline:
        run_loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
    return bool(result["granted"])


def _ensure_access() -> bool:
    status = _EK.EKEventStore.authorizationStatusForEntityType_(_ENTITY_EVENT)
    if status == _FULL_ACCESS:
        return True
    if status == 0:  # notDetermined — prompt once
        return _request_access(_new_store())
    return False  # denied or restricted


# (label, start, end) for a spoken range. Deterministic and pure so it can be
# unit-tested without Calendar access.
def _parse_range(when: str, now: datetime | None = None) -> tuple[str, datetime, datetime]:
    now = now or datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    w = (when or "").lower().strip()

    if "tomorrow" in w:
        start = today + timedelta(days=1)
        return "tomorrow", start, start + timedelta(days=1)
    if "week" in w or "next 7" in w or "7 days" in w:
        return "this week", today, today + timedelta(days=7)
    if "month" in w:
        return "this month", today, today + timedelta(days=30)
    # default / "today" / "" — the whole day (from midnight), so a meeting
    # earlier today still shows up, not just upcoming ones.
    return "today", today, today + timedelta(days=1)


def _to_nsdate(dt: datetime) -> "NSDate":
    return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def _spoken_time(dt: datetime) -> str:
    fmt = "%I %p" if dt.minute == 0 else "%I:%M %p"
    return dt.strftime(fmt).lstrip("0")


def _format_events(events: list, label: str) -> str:
    if not events:
        return f"Nothing on your calendar {label}, Sir."

    parsed = []
    for ev in events:
        start = datetime.fromtimestamp(ev.startDate().timeIntervalSince1970())
        title = (ev.title() or "Untitled").strip()
        all_day = bool(ev.isAllDay()) if hasattr(ev, "isAllDay") else False
        parsed.append((start, title, all_day))
    parsed.sort(key=lambda e: e[0])

    count = len(parsed)
    noun = "thing" if count == 1 else "things"
    lines = []
    for start, title, all_day in parsed:
        when = "all day" if all_day else _spoken_time(start)
        # For a multi-day range, prefix the weekday so it's unambiguous.
        if label != "today":
            when = f"{start.strftime('%A')} {when}" if not all_day else f"{start.strftime('%A')} all day"
        lines.append(f"{when}, {title}")
    return f"You have {count} {noun} {label}, Sir. " + ". ".join(lines) + "."


def get_calendar(timeframe: str = "") -> str:
    """Read the user's macOS Calendar for a time range ('today', 'tomorrow',
    'this week') and return a spoken-ready summary."""
    try:
        if not _ensure_access():
            return ("I don't have access to your calendar yet, Sir. Grant it under "
                    "System Settings, Privacy and Security, Calendars.")
        label, start, end = _parse_range(timeframe)
        store = _new_store()
        predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
            _to_nsdate(start), _to_nsdate(end), None
        )
        events = list(store.eventsMatchingPredicate_(predicate) or [])
        return _format_events(events, label)
    except Exception as e:
        return f"I couldn't read your calendar, Sir: {e}"
