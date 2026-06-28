"""Session 'working set' of code we're discussing + follow-up answering.

The agent re-read a file and re-emitted a generic summary every time, so
follow-ups ("how does the rate limiting work?", "is it secure?") never got a
specific answer. This module keeps recently-read files in memory and answers a
follow-up DIRECTLY from them — no re-reading, no fresh agent loop — and routes
DEEP questions to the cloud brain for better comprehension.
"""
from __future__ import annotations

import os
import re
from collections import OrderedDict

_MAX_FILES = 4
_MAX_CHARS = 16000
_files: "OrderedDict[str, str]" = OrderedDict()  # path -> content, most-recent last


# ── working set ──────────────────────────────────────────────────────────────
def remember_file(path: str, content: str) -> None:
    if not path or not content:
        return
    _files[path] = content
    _files.move_to_end(path)
    while len(_files) > _MAX_FILES:
        _files.popitem(last=False)


def record_tool(name: str, args: dict, result) -> None:
    """Capture file contents read by read_file / read_project_file into the set."""
    if not isinstance(result, str):
        return
    if name == "read_project_file":
        first, _, body = result.partition("\n\n")  # "File: <path> (project: X)\n\n<code>"
        m = re.match(r"^File:\s*(\S+)", first)
        if m and body:
            remember_file(m.group(1), body)
    elif name == "read_file":
        path = (args or {}).get("path", "")
        if path and not result.lstrip().lower().startswith(("error", "file not found")):
            remember_file(path, result)


def clear() -> None:
    _files.clear()


def has_context() -> bool:
    return bool(_files)


def current_context(max_chars: int = _MAX_CHARS) -> str:
    out, used = [], 0
    for path, content in reversed(_files.items()):  # most recent first
        chunk = f"File: {path}\n{content}\n"
        if used + len(chunk) > max_chars:
            chunk = chunk[: max_chars - used]
        out.append(chunk)
        used += len(chunk)
        if used >= max_chars:
            break
    return "\n".join(out)


# ── follow-up detection ──────────────────────────────────────────────────────
_REFERS_BACK = ("it", "this", "that", "they", "them", "the code", "the file",
                "the function", "the endpoint", "the class", "the method",
                "here", "above")
_CODE_TERMS = ("function", "endpoint", "route", "class", "method", "variable",
               "rate limit", "rate-limit", "redis", "database", "db", "query",
               "import", "decorator", "async", "exception", "error handling",
               "security", "secure", "bug", "test", "logic", "flow", "schema")
_NEW_TARGET = ("find ", "open ", "go to ", "another project", "different project",
               "new project", "list ", "downloads", "desktop")
_QUESTION_STARTS = ("how", "why", "what", "where", "which", "who", "is ", "are ",
                    "does ", "do ", "can ", "could ", "should ", "would ",
                    "explain", "tell me", "walk me", "show me", "describe", "is it")


_STOPWORDS = {"what", "does", "this", "that", "code", "file", "function", "work",
              "works", "with", "from", "into", "your", "have", "here", "there",
              "when", "where", "which", "explain", "about", "they", "them", "main"}


def _mentions_symbol(text: str) -> bool:
    """True if the question names an identifier that appears in the read code
    (e.g. 'simpleConnectionPool', 'rate_limit') — a strong follow-up signal."""
    ctx = "".join(_files.values()).lower()
    if not ctx:
        return False
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]+", text):
        low = tok.lower()
        if len(low) >= 5 and low not in _STOPWORDS and low in ctx:
            return True
    return False


def is_followup(text: str) -> bool:
    """True if this is a question ABOUT the code already in the working set
    (so answer from it), not a request to go find/open something new."""
    if not has_context():
        return False
    t = text.lower().strip()
    if any(k in f" {t} " for k in _NEW_TARGET):
        return False
    is_question = t.endswith("?") or t.startswith(_QUESTION_STARTS)
    if not is_question:
        return False
    refers_back = any(f" {r} " in f" {t} " for r in _REFERS_BACK)
    codey = any(k in t for k in _CODE_TERMS)
    return refers_back or codey or _mentions_symbol(text)


# ── depth → cloud routing ────────────────────────────────────────────────────
_DEEP = ("why", "how does", "how is", "how do", "explain", "in detail",
         "walk me through", "trade-off", "tradeoff", "secure", "security",
         "vulnerab", "is it correct", "is this correct", "any bug", "bugs",
         "edge case", "edge-case", "refactor", "improve", "optimi", "design",
         "architecture", "what happens if", "deep dive", "think hard", "thorough",
         "scalab", "race condition", "concurren")
_FORCE_LOCAL = os.getenv("FRIDAY_FORCE_LOCAL", "0") == "1"


def is_deep_question(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in _DEEP)


def should_use_cloud(text: str) -> bool:
    """Deep question + cloud available + not forced local."""
    if _FORCE_LOCAL:
        return False
    if not is_deep_question(text):
        return False
    from brain.llm import cloud_available
    return cloud_available()


def answer_followup(text: str) -> tuple[str, bool]:
    """Answer a follow-up from the working set. Returns (answer, used_cloud)."""
    from brain.llm import ask
    use_cloud = should_use_cloud(text)
    system = (
        "You are FRIDAY answering a follow-up question about code already shown on "
        "the user's screen. Answer SPECIFICALLY and concretely using the code below "
        "— cite the actual functions/lines/logic. Do NOT give a generic overview or "
        "say 'you've shared a script'. If the code doesn't cover it, say so."
    )
    prompt = f"Code we are discussing:\n\n{current_context()}\n\nQuestion: {text}"
    answer = ask(prompt, system=system, use_cloud=use_cloud)
    return answer, use_cloud
