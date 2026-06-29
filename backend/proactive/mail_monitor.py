"""Mail monitor — a proactive trigger kind that watches the user's Gmail and
speaks up only when NEW mail matching the user's own criteria arrives.

This is the real daily-driver win: not "read my inbox on demand" but "tell me,
hands-free, when something I care about lands." It's the web-monitor pattern
(proactive/monitors.py) pointed at Gmail instead of the web — same scheduler,
same restraint:

  1. The user's criteria already DEFINE importance (is:starred, is:important,
     from:boss@x.com), so unlike the noisy web monitor we don't need a brain
     judge — any new match is, by definition, worth one line.
  2. Message-ID dedup (state["seen"]) so a mail is announced exactly once.
  3. The first poll only primes the baseline, so a fresh watch doesn't dump the
     existing inbox at you.

State lives on the Trigger (persisted), so the seen-set survives restarts.
"""
from __future__ import annotations

from typing import Callable, Optional

from tools.gmail_tool import fetch_matching_emails
from proactive.scheduler import register_kind, Trigger

_MAX_SEEN = 80


def _format_alert(new_mails: list[dict], label: str) -> str:
    label = (label + " ").strip() + " " if label else ""
    first = new_mails[0]
    if len(new_mails) == 1:
        return f"Sir, a new {label}email from {first['sender']}: {first['subject']}."
    return (f"Sir, {len(new_mails)} new {label}emails, including one from "
            f"{first['sender']}: {first['subject']}.")


def check_mail_monitor(
    trigger: Trigger,
    fetch_fn: Callable[[str], list[dict]] = fetch_matching_emails,
) -> Optional[str]:
    """Scheduler action for kind='mail_monitor'. Returns a line to speak, or None.

    fetch_fn is injectable so the prime/dedup logic can be unit-tested without a
    real inbox (see test_proactive.py)."""
    st = trigger.state
    criteria = st.get("criteria")
    if not criteria:
        return None

    mails = fetch_fn(criteria)
    keys = [m.get("id", "") for m in mails if m.get("id")]
    seen = set(st.get("seen", []))
    new_mails = [m for m in mails if m.get("id") and m["id"] not in seen]

    # Remember everything seen this poll (even if we don't alert), capped.
    merged = list(st.get("seen", [])) + [k for k in keys if k not in seen]
    st["seen"] = merged[-_MAX_SEEN:]

    # First poll establishes the baseline — never announce the existing inbox.
    if not st.get("primed"):
        st["primed"] = True
        return None

    if not new_mails:
        return None
    return _format_alert(new_mails, st.get("label", ""))


register_kind("mail_monitor", action=check_mail_monitor)
