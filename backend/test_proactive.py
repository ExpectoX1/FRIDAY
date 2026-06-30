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


def test_mail_monitor():
    """Mail monitor primes silently, announces each NEW message once, and never
    re-announces a seen one. No account, no network (fetch is stubbed)."""
    from proactive.mail_monitor import check_mail_monitor

    fails = []
    inbox = {"mails": [{"id": "<a@x>", "sender": "Priya", "subject": "Lunch?"}]}

    def fetch_fn(_criteria):
        return inbox["mails"]

    t = Trigger(message="watch email: starred", fire_at=0, kind="mail_monitor",
                state={"criteria": "is:starred", "label": "starred", "seen": [], "primed": False})

    # 1st poll primes the baseline — existing mail is NOT announced.
    if check_mail_monitor(t, fetch_fn) is not None:
        fails.append("mail monitor announced the existing inbox on priming")

    # No new mail -> silent.
    if check_mail_monitor(t, fetch_fn) is not None:
        fails.append("mail monitor spoke with no new mail")

    # New mail arrives -> one alert naming the sender.
    inbox["mails"] = [{"id": "<b@x>", "sender": "Boss", "subject": "Q3 numbers"}] + inbox["mails"]
    alert = check_mail_monitor(t, fetch_fn)
    if not alert or "Boss" not in alert or "Q3 numbers" not in alert:
        fails.append(f"mail monitor did not announce the new mail: {alert!r}")

    # Same inbox again -> already seen -> silent.
    if check_mail_monitor(t, fetch_fn) is not None:
        fails.append("mail monitor re-announced an already-seen mail")
    return fails


def test_clipboard_monitor():
    """Clipboard monitor primes silently, fires once per NEW useful copy, stays
    silent on unchanged or non-useful (secret/trivial) content. Signature stubbed."""
    from proactive.clipboard_monitor import check_clipboard_monitor

    fails = []
    clip = {"sig": ("h0", None, None)}  # whatever's already copied at startup

    def sig_fn():
        return clip["sig"]

    t = Trigger(message="clipboard watch", fire_at=0, kind="clipboard_monitor",
                state={"last_hash": "", "primed": False})

    # 1st poll primes the baseline — never fire on existing clipboard.
    if check_clipboard_monitor(t, sig_fn) is not None:
        fails.append("clipboard monitor fired on its priming poll")

    # New, useful copy -> offer spoken once.
    clip["sig"] = ("h1", "error", "Sir, that looks like an error trace — want me to take a look?")
    offer = check_clipboard_monitor(t, sig_fn)
    if not offer or "error trace" not in offer:
        fails.append(f"clipboard monitor did not offer on new useful content: {offer!r}")

    # Same clipboard again -> unchanged -> silent.
    if check_clipboard_monitor(t, sig_fn) is not None:
        fails.append("clipboard monitor re-fired on unchanged clipboard")

    # New copy but not useful (secret/trivial -> category None) -> silent.
    clip["sig"] = ("h2", None, None)
    if check_clipboard_monitor(t, sig_fn) is not None:
        fails.append("clipboard monitor fired on non-useful content")
    return fails


def test_notification_monitor():
    """Notification monitor baselines to the current high-water rec_id (never
    announces the existing backlog), then announces only NEW notifications from
    watched sources, deduped by rec_id. DB/FDA stubbed via injected fns."""
    from proactive.notification_monitor import check_notification_monitor

    fails = []
    state = {"max": 100, "new": []}  # what the fake DB reports

    def max_fn():
        return state["max"]

    def fetch_fn(after):
        items = [n for n in state["new"] if n["rec_id"] > after]
        new_max = max([after] + [n["rec_id"] for n in items])
        return new_max, items

    t = Trigger(message="notification watch", fire_at=0, kind="notification_monitor",
                state={"sources": ["whatsapp", "instagram"], "last_rec_id": 0, "primed": False})

    # 1st poll primes to current max (100) — silent, ignores the backlog.
    if check_notification_monitor(t, fetch_fn, max_fn) is not None:
        fails.append("notification monitor announced the backlog on priming")
    if t.state["last_rec_id"] != 100:
        fails.append("notification monitor did not baseline to current max rec_id")

    # New WhatsApp message arrives -> announced once, naming the sender.
    state["new"] = [{"rec_id": 101, "bundle": "net.whatsapp.WhatsApp",
                     "title": "Mom", "body": "call me", "subtitle": "", "iden": ""}]
    alert = check_notification_monitor(t, fetch_fn, max_fn)
    if not alert or "Mom" not in alert or "WhatsApp" not in alert:
        fails.append(f"notification monitor did not announce new WhatsApp message: {alert!r}")

    # Same state -> already past that rec_id -> silent.
    if check_notification_monitor(t, fetch_fn, max_fn) is not None:
        fails.append("notification monitor re-announced an already-seen message")

    # New but non-watched source (a Myntra deal via Chrome) -> silent.
    state["new"] = [{"rec_id": 102, "bundle": "com.google.Chrome",
                     "title": "Shop deals", "body": "50% off", "subtitle": "myntra.com", "iden": ""}]
    if check_notification_monitor(t, fetch_fn, max_fn) is not None:
        fails.append("notification monitor announced an unwatched source")
    return fails


def test_briefing():
    """Briefing weaves only the available sections (calendar/mail/reminders) onto
    the greeting, degrades to a clean 'clear start' line when nothing's available,
    and scheduling registers a recurring 'briefing' trigger. Sections + scheduler
    are stubbed so there's no Calendar/IMAP access or real reminders.json write."""
    import tools.briefing as briefing
    import tools.briefing_tool as briefing_tool

    fails = []

    # Compose: greeting + whatever sections return text (None ones dropped).
    orig = (briefing._calendar_section, briefing._mail_section, briefing._reminders_section)
    briefing._calendar_section = lambda: "You have 2 things on today: standup at 10 AM, review at 4 PM."
    briefing._mail_section = lambda: "5 unread emails, the most recent from Priya."
    briefing._reminders_section = lambda: None
    try:
        out = briefing.build_briefing()
        if "Good " not in out or "Sir" not in out:
            fails.append(f"briefing missing greeting: {out!r}")
        if "standup at 10 AM" not in out or "Priya" not in out:
            fails.append(f"briefing dropped an available section: {out!r}")
        if "reminders today" in out:
            fails.append("briefing invented a reminders line when that section was empty")

        # Nothing available -> a graceful clear-start line, never empty.
        briefing._calendar_section = lambda: None
        briefing._mail_section = lambda: None
        briefing._reminders_section = lambda: None
        out2 = briefing.build_briefing()
        if "clear start" not in out2.lower():
            fails.append(f"empty briefing not graceful: {out2!r}")
    finally:
        briefing._calendar_section, briefing._mail_section, briefing._reminders_section = orig

    # check_briefing (the scheduler action) just returns the composed briefing.
    # briefing_monitor / briefing_tool each bound build_briefing at import, so we
    # patch it in THEIR namespaces (not tools.briefing) to keep the stub real-free.
    import proactive.briefing_monitor as bmon
    from proactive.scheduler import Trigger
    real_build_mon = bmon.build_briefing
    real_build_tool = briefing_tool.build_briefing
    bmon.build_briefing = lambda: "Good morning, Sir."
    briefing_tool.build_briefing = lambda: "Good morning, Sir."

    spoken = bmon.check_briefing(Trigger(message="daily briefing", fire_at=0, kind="briefing"))
    if spoken != "Good morning, Sir.":
        fails.append(f"check_briefing did not return the briefing: {spoken!r}")

    # Scheduling path: 'every morning at 8' -> one recurring 'briefing' trigger,
    # and re-scheduling replaces rather than stacking. Use a temp scheduler so we
    # never touch the real reminders.json.
    with tempfile.TemporaryDirectory() as d:
        from proactive.scheduler import Scheduler
        temp = Scheduler(store_path=Path(d) / "reminders.json")
        temp.init(speak=lambda _t: None)
        real_sched = briefing_tool.scheduler
        briefing_tool.scheduler = temp
        try:
            r1 = briefing_tool.daily_briefing("every morning at 8")
            if not isinstance(r1, dict) or r1.get("status") != "success":
                fails.append(f"scheduling a briefing did not succeed: {r1!r}")
            briefing_tool.daily_briefing("every day at 7am")  # re-schedule
            briefings = [t for t in temp.list_pending() if t.kind == "briefing"]
            if len(briefings) != 1:
                fails.append(f"expected exactly one briefing trigger, got {len(briefings)}")
            elif not briefings[0].recurrence or briefings[0].recurrence.get("kind") != "daily":
                fails.append(f"briefing trigger not recurring daily: {briefings[0].recurrence!r}")

            # No time -> brief now: returns spoken text, schedules nothing.
            before = len([t for t in temp.list_pending() if t.kind == "briefing"])
            now_out = briefing_tool.daily_briefing("")
            if not isinstance(now_out, str):
                fails.append(f"on-demand briefing should return spoken text, got {type(now_out)}")
            after = len([t for t in temp.list_pending() if t.kind == "briefing"])
            if after != before:
                fails.append("on-demand briefing scheduled a trigger it shouldn't have")
        finally:
            briefing_tool.scheduler = real_sched
    # Restore the patched composer references.
    bmon.build_briefing = real_build_mon
    briefing_tool.build_briefing = real_build_tool
    return fails


def run():
    all_fails = []
    for name, fn in [
        ("timeparse", test_timeparse),
        ("scheduler fires", test_scheduler_fires),
        ("persistence", test_scheduler_persistence),
        ("recurring", test_recurring_reschedules),
        ("web monitor", test_web_monitor),
        ("mail monitor", test_mail_monitor),
        ("clipboard monitor", test_clipboard_monitor),
        ("notification monitor", test_notification_monitor),
        ("briefing", test_briefing),
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
