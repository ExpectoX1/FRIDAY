"""Notification monitor — proactively announces incoming messages by watching
the macOS Notification Center (see tools/notifications_tool.py).

The headline daily-driver feature, done safely: instead of integrating each
app's API, FRIDAY watches the notifications your Mac already shows, so WhatsApp,
Instagram, and anything else are covered at once, with no ToS/ban risk.

Same restraint as the other monitors: primes to the current high-water rec_id
(never announces what was already there), only speaks for the user's watched
sources, and dedups by rec_id.
"""
from __future__ import annotations

from typing import Callable, Optional

from tools.notifications_tool import (
    fetch_new, current_max_rec_id, matches, source_label, DEFAULT_SOURCES,
)
from proactive.scheduler import register_kind, Trigger


def _format_alert(items: list[dict], sources: list[str]) -> str:
    first = items[0]
    label = source_label(first, sources)
    who = first["title"] or label
    preview = f": {first['body']}" if first["body"] else ""
    if len(items) == 1:
        return f"Sir, a {label} message from {who}{preview}."
    return (f"Sir, {len(items)} new messages, including a {label} one "
            f"from {who}{preview}.")


def check_notification_monitor(
    trigger: Trigger,
    fetch_fn: Callable[[int], tuple[int, list[dict]]] = fetch_new,
    max_fn: Callable[[], int] = current_max_rec_id,
) -> Optional[str]:
    """Scheduler action for kind='notification_monitor'. Returns a line to speak,
    or None. fetch_fn/max_fn are injectable for tests."""
    st = trigger.state
    sources = st.get("sources") or list(DEFAULT_SOURCES)

    # First poll baselines to the newest existing notification — never announce
    # the backlog that was already on screen when the watch started.
    if not st.get("primed"):
        st["last_rec_id"] = max_fn()
        st["primed"] = True
        return None

    new_max, items = fetch_fn(st.get("last_rec_id", 0))
    st["last_rec_id"] = new_max

    hits = [n for n in items if matches(n, sources)]
    if not hits:
        return None
    return _format_alert(hits, sources)


register_kind("notification_monitor", action=check_notification_monitor)
