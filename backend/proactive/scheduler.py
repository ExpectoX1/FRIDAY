"""Background scheduler + trigger registry for FRIDAY's proactive layer.

A single daemon thread owns a list of *triggers* and, once per tick, asks each
registered trigger-kind "are you due?". When one fires, FRIDAY speaks the
trigger's message through an injected callback (which rides the normal TTS
pipeline), then the trigger is either rescheduled (recurring) or retired.

Why a registry instead of hard-coding reminders: Phase 5 only needs time-based
triggers, but the same machinery should later carry event triggers (an app
opened, a file changed, a calendar item). Each kind registers a `due` predicate
via register_kind(); adding a new proactive behavior is then additive and never
touches the loop.

Triggers persist to ~/FRIDAY/reminders.json so a restart doesn't drop a pending
reminder; overdue one-shots fire once on startup ("while you were away").
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable, Optional

STORE_PATH = Path.home() / "FRIDAY" / "reminders.json"
TICK_SECONDS = 1.0


@dataclass
class Trigger:
    message: str                     # what FRIDAY says when it fires (for speak kinds)
    fire_at: float                   # epoch seconds of the next firing
    kind: str = "reminder"           # reminder | timer | monitor | (future kinds)
    recurrence: Optional[dict] = None
    label: str = ""                  # optional name for cancel-by-name
    state: dict = field(default_factory=dict)  # kind-specific persisted data (e.g. a monitor's seen-set)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Trigger":
        known = {f: d[f] for f in cls.__dataclass_fields__ if f in d}
        return cls(**known)


# A trigger kind is defined by two callables:
#   predicate(trigger, now) -> bool        : is it time to evaluate this trigger?
#   action(trigger) -> Optional[str]       : evaluate it; return text to SPEAK,
#                                            or None to stay silent this time.
# Time-based reminders/timers share _time_due and just speak their phrasing.
# A monitor reuses _time_due (fires on its interval) but its action does the
# real work — poll the web, judge novelty, and return an alert only when one is
# warranted. New proactive behaviors register a kind here and never touch the loop.
def _time_due(trigger: Trigger, now: float) -> bool:
    return now >= trigger.fire_at


def _speak_message(trigger: Trigger) -> Optional[str]:
    return _phrase_for(trigger)


_KIND_PREDICATES: dict[str, Callable[[Trigger, float], bool]] = {
    "reminder": _time_due,
    "timer": _time_due,
}
_KIND_ACTIONS: dict[str, Callable[[Trigger], Optional[str]]] = {
    "reminder": _speak_message,
    "timer": _speak_message,
}

# Kinds that should replay on startup if their time passed while FRIDAY was
# offline (a missed reminder matters; a missed monitor poll does not — it just
# rolls forward and polls fresh).
_REPLAY_ON_STARTUP = {"reminder", "timer"}


def register_kind(
    kind: str,
    action: Callable[[Trigger], Optional[str]],
    predicate: Callable[[Trigger, float], bool] = _time_due,
) -> None:
    """Register a new trigger kind: an `action` (returns text to speak or None)
    and an optional due-`predicate` (defaults to time-based). Extensibility hook —
    adding a proactive behavior is additive and never touches the scheduler loop."""
    _KIND_ACTIONS[kind] = action
    _KIND_PREDICATES[kind] = predicate


class Scheduler:
    def __init__(self, store_path: Path = STORE_PATH):
        self._triggers: list[Trigger] = []
        self._lock = threading.RLock()
        self._speak: Optional[Callable[[str], None]] = None
        self._store_path = store_path
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._started = False

    # ── lifecycle ────────────────────────────────────────────────────────
    def init(self, speak: Callable[[str], None]) -> None:
        """Wire the speak callback and load persisted triggers. Idempotent."""
        self._speak = speak
        self._load()

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._fire_overdue_on_startup()
        self._thread = threading.Thread(target=self._run, daemon=True, name="proactive-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ── public API (used by tools/reminders.py) ──────────────────────────
    def add(self, trigger: Trigger) -> Trigger:
        with self._lock:
            self._triggers.append(trigger)
            self._save()
        return trigger

    def list_pending(self) -> list[Trigger]:
        with self._lock:
            return sorted(self._triggers, key=lambda t: t.fire_at)

    def cancel(self, which: str) -> Optional[Trigger]:
        """Cancel by id, by (case-insensitive) label, or by 1-based index in the
        pending list. Returns the removed trigger, or None if nothing matched."""
        with self._lock:
            pending = sorted(self._triggers, key=lambda t: t.fire_at)
            target = None
            w = (which or "").strip().lower()
            for t in pending:
                if t.id == w or (t.label and t.label.lower() == w):
                    target = t
                    break
            if target is None and w.isdigit():
                idx = int(w) - 1
                if 0 <= idx < len(pending):
                    target = pending[idx]
            if target is None and len(pending) == 1 and w in ("", "it", "that", "the timer", "the reminder"):
                target = pending[0]
            if target is not None:
                self._triggers.remove(target)
                self._save()
            return target

    def clear(self) -> None:
        with self._lock:
            self._triggers.clear()
            self._save()

    # ── internals ────────────────────────────────────────────────────────
    def _run(self) -> None:
        while not self._stop.is_set():
            self._tick(time.time())
            self._stop.wait(TICK_SECONDS)

    def _tick(self, now: float) -> None:
        due: list[Trigger] = []
        with self._lock:
            for t in list(self._triggers):
                predicate = _KIND_PREDICATES.get(t.kind, _time_due)
                if predicate(t, now):
                    due.append(t)
                    self._reschedule_or_retire(t)
            if due:
                self._save()
        # Actions run outside the lock — a monitor's web search + brain judgment
        # can take seconds and must not block list/cancel/add from other threads.
        for t in due:
            self._fire(t)
        if due:
            with self._lock:
                self._save()  # actions may have mutated trigger.state (monitor seen-set)

    def _reschedule_or_retire(self, t: Trigger) -> None:
        """Caller holds the lock. Recurring triggers advance to their next time;
        one-shots are removed."""
        nxt = _next_recurrence(t, time.time())
        if nxt is None:
            self._triggers.remove(t)
        else:
            t.fire_at = nxt

    def _fire(self, t: Trigger, prefix: str = "") -> None:
        if self._speak is None:
            return
        action = _KIND_ACTIONS.get(t.kind, _speak_message)
        try:
            text = action(t)            # may stay silent (monitor with nothing new)
        except Exception:
            text = None
        if text:
            try:
                self._speak(prefix + text)
            except Exception:
                pass

    def _fire_overdue_on_startup(self) -> None:
        """Fire one-shot triggers whose time passed while FRIDAY was offline, so a
        missed reminder isn't silently lost. Recurring triggers just roll forward."""
        now = time.time()
        overdue: list[Trigger] = []
        with self._lock:
            for t in list(self._triggers):
                if now >= t.fire_at:
                    # Monitors don't replay a missed poll — just roll forward and
                    # poll fresh on the next tick. Only reminders/timers speak.
                    if t.kind in _REPLAY_ON_STARTUP:
                        overdue.append(t)
                    self._reschedule_or_retire(t)
            if overdue or self._triggers:
                self._save()
        for t in overdue:
            self._fire(t, prefix="While you were away — ")

    def _load(self) -> None:
        try:
            raw = json.loads(self._store_path.read_text())
            with self._lock:
                self._triggers = [Trigger.from_dict(d) for d in raw]
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            self._triggers = []

    def _save(self) -> None:
        """Caller holds the lock."""
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            self._store_path.write_text(
                json.dumps([t.to_dict() for t in self._triggers], indent=2)
            )
        except Exception:
            pass


def _next_recurrence(t: Trigger, now: float) -> Optional[float]:
    """Next fire time for a recurring trigger, or None if it's one-shot/done."""
    rec = t.recurrence
    if not rec:
        return None
    from datetime import datetime, timedelta
    if rec.get("kind") == "interval":
        seconds = float(rec.get("seconds", 0))
        if seconds <= 0:
            return None
        nxt = t.fire_at + seconds
        while nxt <= now:
            nxt += seconds
        return nxt
    if rec.get("kind") == "daily":
        now_dt = datetime.fromtimestamp(now)
        target = now_dt.replace(hour=int(rec["hour"]), minute=int(rec["minute"]),
                                second=0, microsecond=0)
        if target.timestamp() <= now:
            target += timedelta(days=1)
        return target.timestamp()
    return None


def _phrase_for(t: Trigger) -> str:
    if t.kind == "timer":
        return f"Sir, your timer is up. {t.message}".strip()
    return f"Sir, a reminder: {t.message}".strip()


# Module-level singleton — tools and main.py share this one scheduler.
scheduler = Scheduler()
