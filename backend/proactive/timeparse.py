"""Natural-language time parsing for reminders and timers.

The brain hands us a free-text "when" string ("in 10 minutes", "at 5:30pm",
"tomorrow at 9am", "every weekday at 8"). We turn that into an absolute fire
time (epoch seconds) plus an optional recurrence rule, without pulling in a
heavy NLP dependency — dateutil (already a transitive dep) handles the absolute
clock-time cases; a small regex layer covers the relative/recurring ones.

parse_when() returns a ParsedTime or None if nothing usable was found, so the
caller can ask the user to rephrase instead of silently scheduling garbage.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

try:
    from dateutil import parser as _dateutil_parser
except Exception:  # pragma: no cover - dateutil ships with several deps
    _dateutil_parser = None


# recurrence is None for one-shot, or a dict the scheduler understands:
#   {"kind": "interval", "seconds": N}             -> every N seconds
#   {"kind": "daily", "hour": H, "minute": M}      -> every day at H:M
@dataclass
class ParsedTime:
    fire_at: float            # epoch seconds of the next firing
    recurrence: Optional[dict]
    pretty: str               # human phrasing for the confirmation ("in 10 minutes")


_UNIT_SECONDS = {
    "second": 1, "seconds": 1, "sec": 1, "secs": 1, "s": 1,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60, "m": 60,
    "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600, "h": 3600,
    "day": 86400, "days": 86400,
    "week": 604800, "weeks": 604800,
}

# "in 10 minutes", "10 mins", "in 1 hour and 30 minutes", "90 seconds"
_REL_RE = re.compile(
    r"(?:in\s+|after\s+)?"
    r"(?P<pairs>(?:\d+(?:\.\d+)?\s*[a-z]+\s*(?:and\s*)?)+)",
    re.IGNORECASE,
)
_PAIR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([a-z]+)", re.IGNORECASE)


def _humanize_delta(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"in {seconds} second{'s' if seconds != 1 else ''}"
    if seconds < 3600:
        m = seconds // 60
        return f"in {m} minute{'s' if m != 1 else ''}"
    if seconds < 86400:
        h = seconds / 3600
        h_str = f"{h:.0f}" if h == int(h) else f"{h:.1f}"
        return f"in {h_str} hour{'s' if h != 1 else ''}"
    d = seconds / 86400
    d_str = f"{d:.0f}" if d == int(d) else f"{d:.1f}"
    return f"in {d_str} day{'s' if d != 1 else ''}"


def _parse_relative(text: str, now: float) -> Optional[ParsedTime]:
    """"in 10 minutes", "90 seconds", "1 hour and 30 minutes"."""
    total = 0.0
    matched_any = False
    for value, unit in _PAIR_RE.findall(text):
        unit = unit.lower()
        if unit not in _UNIT_SECONDS:
            continue
        total += float(value) * _UNIT_SECONDS[unit]
        matched_any = True
    if not matched_any or total <= 0:
        return None
    return ParsedTime(fire_at=now + total, recurrence=None, pretty=_humanize_delta(total))


def _next_daily(hour: int, minute: int, now_dt: datetime) -> datetime:
    target = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now_dt:
        target += timedelta(days=1)
    return target


def _parse_recurring(text: str, now_dt: datetime) -> Optional[ParsedTime]:
    """"every day at 8am", "every morning", "each day at 18:30"."""
    if not re.search(r"\b(every|each)\b", text):
        return None
    clock = _extract_clock(text)
    if clock is None:
        # "every morning" / "every evening" defaults
        if "morning" in text:
            clock = (8, 0)
        elif "afternoon" in text:
            clock = (14, 0)
        elif "evening" in text or "night" in text:
            clock = (20, 0)
        else:
            return None
    hour, minute = clock
    target = _next_daily(hour, minute, now_dt)
    pretty = f"every day at {_fmt_clock(hour, minute)}"
    return ParsedTime(
        fire_at=target.timestamp(),
        recurrence={"kind": "daily", "hour": hour, "minute": minute},
        pretty=pretty,
    )


_CLOCK_RE = re.compile(
    r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b"
    r"|\b(?:at\s+)(\d{1,2}):(\d{2})\b",
    re.IGNORECASE,
)


def _extract_clock(text: str) -> Optional[tuple[int, int]]:
    m = _CLOCK_RE.search(text)
    if not m:
        return None
    if m.group(1) is not None:  # 12-hour form with am/pm
        hour = int(m.group(1)) % 12
        minute = int(m.group(2) or 0)
        if m.group(3).lower() == "pm":
            hour += 12
        return hour, minute
    # 24-hour "at 18:30"
    return int(m.group(4)), int(m.group(5))


def _fmt_clock(hour: int, minute: int) -> str:
    suffix = "am" if hour < 12 else "pm"
    h12 = hour % 12 or 12
    if minute:
        return f"{h12}:{minute:02d} {suffix}"
    return f"{h12} {suffix}"


def _parse_absolute(text: str, now: float, now_dt: datetime) -> Optional[ParsedTime]:
    """Clock times and dates: "at 5:30pm", "tomorrow at 9am", "at 18:00"."""
    base = now_dt
    day_offset = 0
    if "tomorrow" in text:
        day_offset = 1
    elif "tonight" in text:
        day_offset = 0

    clock = _extract_clock(text)
    if clock is not None:
        hour, minute = clock
        target = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        target += timedelta(days=day_offset)
        if target.timestamp() <= now:
            target += timedelta(days=1)
        return ParsedTime(fire_at=target.timestamp(), recurrence=None,
                          pretty=f"at {_fmt_clock(hour, minute)}")

    # Last resort: let dateutil try the whole phrase (handles "June 30 at 5pm",
    # "next monday 9am"). fuzzy=True ignores surrounding words.
    if _dateutil_parser is not None:
        try:
            dt = _dateutil_parser.parse(text, default=base, fuzzy=True)
            if dt.timestamp() > now:
                return ParsedTime(fire_at=dt.timestamp(), recurrence=None,
                                  pretty=dt.strftime("on %A at %I:%M %p").replace(" 0", " "))
        except (ValueError, OverflowError):
            pass
    return None


def parse_interval(text: str, default: float = 1800.0) -> float:
    """Parse a polling interval ("every 30 minutes", "15 mins", "1 hour") into
    seconds. Falls back to `default` (30 min) when nothing usable is found, so a
    monitor is never created with a zero/garbage cadence."""
    if not text or not text.strip():
        return default
    total = 0.0
    for value, unit in _PAIR_RE.findall(text.lower()):
        if unit in _UNIT_SECONDS:
            total += float(value) * _UNIT_SECONDS[unit]
    return total if total > 0 else default


def parse_when(when: str, now: Optional[float] = None) -> Optional[ParsedTime]:
    """Parse a free-text time spec into an absolute fire time + recurrence.

    Tries, in order: recurring ("every day at 8") -> relative ("in 10 min") ->
    absolute clock/date ("at 5pm", "tomorrow at 9"). Returns None if nothing
    parses, so the tool can ask the user to rephrase.
    """
    if not when or not when.strip():
        return None
    now = time.time() if now is None else now
    now_dt = datetime.fromtimestamp(now)
    text = when.strip().lower()

    return (
        _parse_recurring(text, now_dt)
        or _parse_relative(text, now)
        or _parse_absolute(text, now, now_dt)
    )
