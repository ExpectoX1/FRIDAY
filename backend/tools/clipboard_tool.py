"""Clipboard companion — let FRIDAY act on whatever you just copied.

A desktop-companion superpower that's only safe because FRIDAY is local: it can
read your clipboard to summarize / explain / translate / fix what you copied,
and (opt-in) proactively offer help when you copy something useful.

Hard privacy rule: clipboards hold passwords. We refuse obvious secrets on the
reactive path, and the proactive watcher ONLY reacts to positively-useful
content (error traces, code, a question, foreign text) — never short tokens or
anything that looks like a credential.

Leaf module: no proactive/registry imports, so proactive/clipboard_monitor.py
can import the signature helper without an import cycle.
"""
from __future__ import annotations

import hashlib
import re
import subprocess

_MAX = 4000

# Words that strongly imply a secret, and the "looks like a key/token" shape.
_SECRET_HINTS = re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|access[_-]?key|token|bearer|"
    r"-----BEGIN|ssh-rsa|nvapi-|sk-[a-z0-9])"
)
_TRACEBACK = re.compile(
    r"(Traceback \(most recent call last\)|^\s*at .+\(.+:\d+\)|\b\w*(Error|Exception)\b:)",
    re.M,
)
# Strong code signals only (keeps prose from misclassifying): braces/semicolons,
# arrows, tags, code-specific keywords, or a function-call `name(...)` with no
# space before the paren (so "store (yesterday)" in prose doesn't match).
_CODE = re.compile(
    r"[{};]|=>|->|</?[a-zA-Z]+>|\b(def|function|import|class|lambda|elif|async|await)\b|\b\w+\([^)]*\)"
)


def _read_raw() -> str:
    try:
        r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _looks_like_secret(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if _SECRET_HINTS.search(t):
        return True
    # One line, no spaces, long, mixed letters+digits → password/key/token shape.
    if "\n" not in t and " " not in t and len(t) >= 16:
        if any(c.isdigit() for c in t) and any(c.isalpha() for c in t):
            return True
    return False


def _classify(text: str) -> tuple[str | None, str | None]:
    """(category, spoken offer) for content worth a PROACTIVE nudge — else
    (None, None). Conservative on purpose: only positively-useful kinds, never
    secrets or trivial scraps, so the watcher stays a delight, not a nag."""
    t = text.strip()
    if not t or len(t) < 12 or _looks_like_secret(t):
        return None, None
    if _TRACEBACK.search(t):
        return "error", "Sir, that looks like an error trace — want me to take a look?"
    if t.endswith("?") and len(t) < 300:
        return "question", "Want me to answer that, Sir?"
    letters = [c for c in t if c.isalpha()]
    if letters and sum(1 for c in letters if ord(c) > 127) / len(letters) > 0.3:
        return "foreign", "Want me to translate that, Sir?"
    if "\n" in t and _CODE.search(t):
        return "code", "Want me to explain that snippet, Sir?"
    return None, None


def read_clipboard() -> str:
    """Return the current clipboard text so the brain can act on it (summarize,
    explain, translate, fix). Refuses obvious secrets."""
    text = _read_raw().strip()
    if not text:
        return "Your clipboard is empty, Sir."
    if _looks_like_secret(text):
        return "That looks like a password or key, Sir — I won't read it back."
    return text[:_MAX]


def clipboard_signature() -> tuple[str, str | None, str | None]:
    """(content hash, category, offer) of the current clipboard, for the monitor."""
    text = _read_raw()
    h = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]
    cat, offer = _classify(text)
    return h, cat, offer
