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
    message: str                     # what FRIDAY says when it fires
    fire_at: float                   # epoch seconds of the next firing
    kind: str = "reminder"           # reminder | timer | (future: event kinds)
    recurrence: Optional[dict] = None
    label: str = ""                  # optional name for cancel-by-name
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Trigger":
        known = {f: d[f] for f in cls.__dataclass_fields__ if f in d}
        return cls(**known)


# kind -> predicate(trigger, now) -> bool. Time-based kinds share one predicate;
# future event kinds register their own without touching the loop.
def _time_due(trigger: Trigger, now: float) -> bool:
    return now >= trigger.fire_at


_KIND_PREDICATES: dict[str, Callable[[Trigger, float], bool]] = {
    "reminder": _time_due,
    "timer": _time_due,
}


def register_kind(kind: str, predicate: Callable[[Trigger, float], bool]) -> None:
    """Register a new trigger kind with its own due-predicate (extensibility hook)."""
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
        for t in due:
            self._fire(t)

    def _reschedule_or_retire(self, t: Trigger) -> None:
        """Caller holds the lock. Recurring triggers advance to their next time;
        one-shots are removed."""
        nxt = _next_recurrence(t, time.time())
        if nxt is None:
            self._triggers.remove(t)
        else:
            t.fire_at = nxt

    def _fire(self, t: Trigger) -> None:
        if self._speak is None:
            return
        try:
            self._speak(_phrase_for(t))
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
                    overdue.append(t)
                    self._reschedule_or_retire(t)
            if overdue:
                self._save()
        for t in overdue:
            if self._speak is not None:
                try:
                    self._speak("While you were away — " + _phrase_for(t))
                except Exception:
                    pass

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
