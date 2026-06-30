"""Daily briefing — composes the data FRIDAY already has (calendar, mail,
reminders) into one short spoken rundown. This is the "feels alive every
morning" win: not three separate tool calls but a single, woven summary.

Leaf module by design: it only reads the *data* layers (calendar_tool,
gmail_tool, scheduler) and never imports the proactive registry or a tool that
imports it, so proactive/briefing_monitor.py can `from tools.briefing import
build_briefing` without an import cycle (mirrors gmail_tool ← mail_monitor).

Every section degrades gracefully: no calendar access or no Gmail credentials
just omits that line rather than nagging the user three times.
"""
from __future__ import annotations

from datetime import datetime


def _ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _spoken_time(fire_at: float) -> str:
    dt = datetime.fromtimestamp(fire_at)
    fmt = "%I %p" if dt.minute == 0 else "%I:%M %p"
    return dt.strftime(fmt).lstrip("0")


def _greeting(now: datetime | None = None) -> str:
    now = now or datetime.now()
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    return (f"Good {part}, Sir. It's {now.strftime('%A')}, "
            f"{now.strftime('%B')} {_ordinal(now.day)}.")


def _calendar_section() -> str | None:
    """Today's events as one concise line, or None if calendar is inaccessible.
    Reads the EventKit store directly (calendar_tool internals) so the briefing
    can phrase its own compact line instead of get_calendar's standalone one."""
    try:
        from tools import calendar_tool as cal
        if not cal._ensure_access():
            return None
        _label, start, end = cal._parse_range("today")
        store = cal._new_store()
        predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
            cal._to_nsdate(start), cal._to_nsdate(end), None
        )
        events = list(store.eventsMatchingPredicate_(predicate) or [])
    except Exception:
        return None

    if not events:
        return "Your calendar's clear today."

    parsed = []
    for ev in events:
        try:
            s = datetime.fromtimestamp(ev.startDate().timeIntervalSince1970())
            title = (ev.title() or "Untitled").strip()
            all_day = bool(ev.isAllDay()) if hasattr(ev, "isAllDay") else False
            parsed.append((s, title, all_day))
        except Exception:
            continue
    if not parsed:
        return "Your calendar's clear today."
    parsed.sort(key=lambda e: e[0])

    count = len(parsed)
    noun = "thing" if count == 1 else "things"
    items = []
    for s, title, all_day in parsed[:4]:
        when = "all day" if all_day else _spoken_time(s.timestamp())
        items.append(f"{title} {('' if all_day else 'at ')}{when}".strip())
    more = "" if count <= 4 else f", and {count - 4} more"
    return f"You have {count} {noun} on today: " + ", ".join(items) + more + "."


def _mail_section() -> str | None:
    """Recent unread mail as one line, or None if Gmail isn't set up."""
    try:
        from tools.gmail_tool import _creds, _fetch, _to_gmail_query
        if _creds() is None:
            return None
        query, _label = _to_gmail_query("unread")
        total, mails = _fetch(query, 5)
    except Exception:
        return None

    if total == 0 or not mails:
        return "No new unread email."
    latest = mails[0]
    if total == 1:
        return f"One unread email, from {latest['sender']}: {latest['subject']}."
    return f"{total} unread emails, the most recent from {latest['sender']}."


def _reminders_section() -> str | None:
    """Reminders and timers due before end of today, or None if none."""
    try:
        from proactive.scheduler import scheduler
        end_of_day = datetime.now().replace(
            hour=23, minute=59, second=59, microsecond=0).timestamp()
        pending = [t for t in scheduler.list_pending()
                   if t.kind in ("reminder", "timer") and t.fire_at <= end_of_day]
    except Exception:
        return None

    if not pending:
        return None
    if len(pending) == 1:
        t = pending[0]
        return f"One reminder today: {t.message} at {_spoken_time(t.fire_at)}."
    items = ", ".join(f"{t.message} at {_spoken_time(t.fire_at)}" for t in pending[:3])
    more = "" if len(pending) <= 3 else f", and {len(pending) - 3} more"
    return f"You have {len(pending)} reminders today: {items}{more}."


def build_briefing() -> str:
    """The spoken daily briefing: greeting + whatever of calendar/mail/reminders
    is available. Pure composition over the data layers — safe to call on demand
    or from the scheduled briefing trigger."""
    sections = [s for s in (_calendar_section(), _mail_section(), _reminders_section()) if s]
    if not sections:
        return _greeting() + " Nothing pressing on your calendar or in your inbox — a clear start to the day."
    return _greeting() + " " + " ".join(sections)
