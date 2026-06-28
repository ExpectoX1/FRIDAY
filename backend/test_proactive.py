"""Unit tests for the proactive layer — time parsing + scheduler firing.

No LLM, no real sleeps: the scheduler is ticked with an injected clock so a
"10 minute" reminder fires deterministically in microseconds.

    python test_proactive.py

Exits non-zero on any failure.
"""
import sys
import time
import tempfile
from pathlib import Path

from proactive.timeparse import parse_when
from proactive.scheduler import Scheduler, Trigger


def _approx(a, b, tol=1.5):
    return abs(a - b) <= tol


def test_timeparse():
    fails = []
    now = time.time()

    def check(spec, want_offset=None, want_recur=None):
        p = parse_when(spec, now=now)
        if p is None:
            fails.append(f"{spec!r} -> None")
            return
        if want_offset is not None and not _approx(p.fire_at - now, want_offset):
            fails.append(f"{spec!r} -> offset {p.fire_at - now:.0f}s, want ~{want_offset}s")
        if want_recur is not None:
            kind = (p.recurrence or {}).get("kind")
            if kind != want_recur:
                fails.append(f"{spec!r} -> recurrence {kind}, want {want_recur}")

    check("in 10 minutes", want_offset=600)
    check("10 mins", want_offset=600)
    check("in 30 seconds", want_offset=30)
    check("in 2 hours", want_offset=7200)
    check("in 1 hour and 30 minutes", want_offset=5400)
    check("every day at 8am", want_recur="daily")
    check("every morning", want_recur="daily")

    # Absolute clock time: should land in the future, same or next day.
    p = parse_when("at 5:30pm", now=now)
    if p is None or p.fire_at <= now:
        fails.append("'at 5:30pm' did not parse to a future time")

    # Garbage -> None (so the tool can ask the user to rephrase).
    if parse_when("sometime later maybe") is not None:
        fails.append("'sometime later maybe' should be unparseable")

    return fails


def test_scheduler_fires():
    fails = []
    spoken = []
    with tempfile.TemporaryDirectory() as d:
        s = Scheduler(store_path=Path(d) / "reminders.json")
        s.init(speak=spoken.append)

        now = 1000.0
        s.add(Trigger(message="call mom", fire_at=now + 600, kind="reminder"))

        s._tick(now + 599)          # not due yet
        if spoken:
            fails.append("fired early")

        s._tick(now + 601)          # due
        if not any("call mom" in m for m in spoken):
            fails.append(f"reminder did not fire: {spoken}")
        if s.list_pending():
            fails.append("one-shot trigger was not retired after firing")
    return fails


def test_scheduler_persistence():
    fails = []
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "reminders.json"
        s1 = Scheduler(store_path=path)
        s1.init(speak=lambda _t: None)
        s1.add(Trigger(message="standup", fire_at=time.time() + 9999, kind="reminder", label="standup"))

        s2 = Scheduler(store_path=path)          # fresh instance, same file
        s2.init(speak=lambda _t: None)
        if len(s2.list_pending()) != 1:
            fails.append("trigger did not persist across instances")

        removed = s2.cancel("standup")           # cancel by label
        if removed is None or s2.list_pending():
            fails.append("cancel-by-label failed")
    return fails


def test_recurring_reschedules():
    fails = []
    spoken = []
    with tempfile.TemporaryDirectory() as d:
        s = Scheduler(store_path=Path(d) / "reminders.json")
        s.init(speak=spoken.append)
        now = time.time()
        s.add(Trigger(message="drink water", fire_at=now - 1, kind="reminder",
                      recurrence={"kind": "interval", "seconds": 3600}))
        s._tick(now)
        if not spoken:
            fails.append("recurring trigger did not fire")
        pending = s.list_pending()
        if len(pending) != 1 or pending[0].fire_at <= now:
            fails.append("recurring trigger did not reschedule into the future")
    return fails


def test_web_monitor():
    """Monitor primes silently, dedups seen results, and only speaks when the
    (stubbed) brain judges a NEW result important. No network, no LLM."""
    from proactive.monitors import check_web_monitor

    fails = []
    results = {"out": "Top Results:\n- A (URL: https://x.com/1)\n- B (URL: https://x.com/2)"}

    def search_fn(_query):
        return results["out"]

    judged = []

    def judge_fn(_q, _out, _last):
        judged.append(1)
        return "Sir, big news just dropped."

    t = Trigger(message="Fabrizio Barcelona", fire_at=0, kind="monitor",
                state={"query": "Fabrizio Barcelona", "seen": [], "primed": False, "last_alert": ""})

    # 1st poll: primes the baseline, must stay silent and not call the judge.
    if check_web_monitor(t, search_fn, judge_fn) is not None:
        fails.append("monitor alerted on its priming poll")
    if judged:
        fails.append("judge called during priming")

    # 2nd poll, nothing new: silent, judge still not called.
    if check_web_monitor(t, search_fn, judge_fn) is not None:
        fails.append("monitor alerted with no new results")
    if judged:
        fails.append("judge called with no new results")

    # New result appears: judge runs and its alert is spoken.
    results["out"] += "\n- C (URL: https://x.com/3)"
    alert = check_web_monitor(t, search_fn, judge_fn)
    if alert != "Sir, big news just dropped.":
        fails.append(f"monitor did not surface new-and-important result: {alert!r}")
    if t.state.get("last_alert") != alert:
        fails.append("last_alert not recorded")

    # Same result again -> already seen -> silent, judge not called again.
    before = len(judged)
    if check_web_monitor(t, search_fn, judge_fn) is not None:
        fails.append("monitor re-alerted on an already-seen result")
    if len(judged) != before:
        fails.append("judge re-ran on an already-seen result")

    # Brain says 'not important' -> stay silent even though the result is new.
    results["out"] += "\n- D (URL: https://x.com/4)"
    if check_web_monitor(t, search_fn, lambda *_: None) is not None:
        fails.append("monitor spoke despite brain judging it unimportant")
    return fails


def run():
    all_fails = []
    for name, fn in [
        ("timeparse", test_timeparse),
        ("scheduler fires", test_scheduler_fires),
        ("persistence", test_scheduler_persistence),
        ("recurring", test_recurring_reschedules),
        ("web monitor", test_web_monitor),
    ]:
        fails = fn()
        status = "PASS" if not fails else "FAIL"
        print(f"  {status}  {name}")
        for f in fails:
            print(f"        - {f}")
        all_fails += fails

    print(f"\n{'ALL PASSED' if not all_fails else f'{len(all_fails)} FAILURES'}")
    sys.exit(1 if all_fails else 0)


if __name__ == "__main__":
    run()
