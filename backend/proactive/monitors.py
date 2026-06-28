"""Web monitor — a proactive trigger kind that watches the web and interrupts
FRIDAY's user only when something genuinely new and important shows up.

This is the "transfer window monitor" generalized: "monitor Fabrizio for
Barcelona news" registers a recurring trigger whose action, each interval,
does:  search the web -> drop results we've already seen -> ask the brain
whether what's left is worth interrupting for -> speak one line, or stay silent.

Two layers of restraint so she isn't a chatterbox:
  1. URL-level dedup (state["seen"]): we never re-surface a result twice.
  2. Brain judgment: even among genuinely new results, qwen3 decides if it's
     important enough to break the user's focus, and phrases the alert.

The first poll only *primes* the seen-set (everything currently on the topic is
"already known"), so a brand-new monitor doesn't immediately dump the status quo.

State lives on the Trigger (persisted to reminders.json), so seen-sets and the
primed flag survive restarts.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

from tools.web import search_web
from proactive.scheduler import register_kind, Trigger

_URL_RE = re.compile(r"https?://[^\s)]+")
_MAX_SEEN = 60  # cap the seen-set so the persisted state can't grow unbounded

# source name -> fetcher(query) -> search_web-style string. Only 'web' ships:
# direct X timeline scraping proved unreliable (X serves automated sessions a
# stale "highlights" view, so a tweet-level monitor would silently never fire).
# The dispatch stays so a reliable source (e.g. a paid tweet API) can drop in
# behind source="x" later without touching the monitor logic.
_SOURCE_FETCHERS = {
    "web": search_web,
}


def _result_keys(search_output: str) -> list[str]:
    """Stable identifiers for the current results — URLs, deduped, order-preserved."""
    seen, keys = set(), []
    for url in _URL_RE.findall(search_output):
        u = url.rstrip(".,);")
        if u not in seen:
            seen.add(u)
            keys.append(u)
    return keys


def _judge_importance(query: str, search_output: str, last_alert: str) -> Optional[str]:
    """Ask the brain whether these (new) results warrant interrupting the user,
    and if so, phrase a single spoken alert. Returns the line, or None to stay
    silent. Runs on the local brain (background, free) regardless of FRIDAY_BRAIN."""
    # Lazy import: brain.llm -> tools.registry -> tools.monitor -> this module,
    # so importing the brain at module load would be circular.
    import ollama
    from brain.llm import MODEL, KEEP_ALIVE

    system = (
        "You are FRIDAY, a personal assistant monitoring a topic for your user "
        "(addressed as 'Sir'). You are given fresh web results. Decide if there is "
        "something GENUINELY NEW and IMPORTANT enough to interrupt the user right now "
        "— a confirmed development, a decision, a result, breaking news. Ignore "
        "speculation, rehashes, and minor chatter. Do NOT repeat what you already "
        "told them. If nothing qualifies, set important=false.\n"
        "When important, write 'alert' as ONE short spoken sentence in FRIDAY's voice "
        "leading with the news (e.g. \"Sir, Fabrizio reports Barcelona have agreed a "
        "fee for Nico Williams.\")."
    )
    user = (
        f"Topic being monitored: {query}\n\n"
        f"Most recent thing you already told the user: {last_alert or '(nothing yet)'}\n\n"
        f"Fresh web results:\n{search_output}"
    )
    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            keep_alive=KEEP_ALIVE,
            think=False,
            format={
                "type": "object",
                "properties": {
                    "important": {"type": "boolean"},
                    "alert": {"type": "string"},
                },
                "required": ["important", "alert"],
            },
        )
        data = json.loads(response.message.content.strip())
        if data.get("important") and data.get("alert", "").strip():
            return data["alert"].strip()
    except Exception:
        return None
    return None


def check_web_monitor(
    trigger: Trigger,
    fetch_fn: Optional[Callable[[str], str]] = None,
    judge_fn: Callable[[str, str, str], Optional[str]] = _judge_importance,
) -> Optional[str]:
    """Scheduler action for kind='monitor'. Returns an alert to speak, or None.

    The source is read from trigger.state and picks the fetcher (only 'web'
    ships today); fetch_fn/judge_fn are injectable so the behavior can be
    unit-tested without network or an LLM (see test_proactive.py)."""
    st = trigger.state
    query = st.get("query") or trigger.message
    if not query:
        return None

    if fetch_fn is None:
        fetch_fn = _SOURCE_FETCHERS.get(st.get("source", "web"), search_web)

    output = fetch_fn(query)
    if not output or output.startswith("Search failed") or output.startswith("No results"):
        return None

    keys = _result_keys(output)
    seen = set(st.get("seen", []))
    new_keys = [k for k in keys if k not in seen]

    # Always remember what we've now seen (even if we don't alert) so the same
    # item never triggers a second brain judgment. Keep the most recent keys.
    merged = list(st.get("seen", [])) + [k for k in keys if k not in seen]
    st["seen"] = merged[-_MAX_SEEN:]

    # First poll just establishes the baseline — never alert on the status quo.
    if not st.get("primed"):
        st["primed"] = True
        return None

    if not new_keys:
        return None

    alert = judge_fn(query, output, st.get("last_alert", ""))
    if alert:
        st["last_alert"] = alert
        return alert
    return None


# Register the kind so the scheduler can fire monitors. Reuses the default
# time-based predicate (monitors fire on their interval); the action above does
# the real work and decides whether to speak.
register_kind("monitor", action=check_web_monitor)
