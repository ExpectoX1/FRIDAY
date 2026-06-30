"""Clipboard monitor — a proactive trigger kind that offers help the moment you
copy something useful (an error trace, code, a question, foreign text).

Same restraint as the other monitors: primes silently (won't fire on whatever
was already on the clipboard), dedups by content hash, and — via _classify in
tools/clipboard_tool — only ever speaks for positively-useful content, never for
passwords or trivial scraps.
"""
from __future__ import annotations

from typing import Callable, Optional

from tools.clipboard_tool import clipboard_signature
from proactive.scheduler import register_kind, Trigger


def check_clipboard_monitor(
    trigger: Trigger,
    sig_fn: Callable[[], tuple[str, Optional[str], Optional[str]]] = clipboard_signature,
) -> Optional[str]:
    """Scheduler action for kind='clipboard_monitor'. Returns an offer to speak,
    or None. sig_fn is injectable for tests (no real clipboard needed)."""
    st = trigger.state
    sig_hash, _category, offer = sig_fn()

    if sig_hash == st.get("last_hash"):
        return None  # clipboard unchanged since last poll
    st["last_hash"] = sig_hash

    # First poll just baselines whatever is already copied — never fire on it.
    if not st.get("primed"):
        st["primed"] = True
        return None

    return offer  # None unless _classify found positively-useful content


register_kind("clipboard_monitor", action=check_clipboard_monitor)
