"""Activity emission + the spoken/displayed split for the coding window.

Two jobs:
  1. emit_tool_activity(): turn a tool's result into structured activity events
     (file_read + code_snippet on reads, file_write + diff on writes, tool_call
     otherwise) so the window can render file/code/diff cards.
  2. deliver_reply(): split a final answer into what's SPOKEN (a short gist) vs
     what's DISPLAYED (the full text). FRIDAY should never read code, reviews, or
     docs aloud — she acks briefly and the full content goes to the window.
"""
from __future__ import annotations

import os
import re

from bridge import state_bus

# Cap code shipped to the UI; the model still gets the full result via the tool
# return — this only bounds the on-screen preview / bandwidth.
_MAX_CODE_CHARS = 12000

_LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".swift": "swift", ".go": "go", ".rs": "rust",
    ".java": "java", ".kt": "kotlin", ".c": "c", ".cc": "cpp", ".cpp": "cpp",
    ".h": "c", ".hpp": "cpp", ".cs": "csharp", ".rb": "ruby", ".php": "php",
    ".sh": "bash", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".md": "markdown", ".html": "html", ".css": "css", ".sql": "sql",
}

_READ_TOOLS = {"read_file", "read_project_file"}
_FILE_HEADER_RE = re.compile(r"^File:\s*(\S+)")


def _language_for(path: str) -> str:
    return _LANG_BY_EXT.get(os.path.splitext(path or "")[1].lower(), "text")


def _clip(code: str) -> str:
    if code and len(code) > _MAX_CODE_CHARS:
        return code[:_MAX_CODE_CHARS] + "\n... [truncated for display]"
    return code


def emit_tool_activity(name: str, args: dict, result) -> None:
    """Publish the activity event(s) for a completed tool call. Best-effort —
    never raises into the caller (a UI hiccup must not break the agent)."""
    try:
        args = args or {}
        result_str = result if isinstance(result, str) else (
            result.get("message", "") if isinstance(result, dict) else str(result))
        failed = isinstance(result, dict) and str(result.get("status")) == "error" \
            or (isinstance(result, str) and result.lstrip().lower().startswith(
                ("error", "no project", "no such", "search failed", "file not found")))

        if failed:
            state_bus.publish_activity("error", result_str[:300], tool=name)
            return

        if name in _READ_TOOLS:
            path, code = _read_payload(name, args, result)
            state_bus.publish_activity("file_read", f"Read {os.path.basename(path) or path}",
                                       path=path, tool=name)
            state_bus.publish_activity("code_snippet", f"{os.path.basename(path) or path}",
                                       path=path, language=_language_for(path), code=_clip(code))

        elif name == "write_file":
            path = args.get("path", "")
            content = args.get("content", "")
            state_bus.publish_activity("file_write", f"Wrote {os.path.basename(path) or path}",
                                       path=path, tool=name)
            state_bus.publish_activity("code_snippet", os.path.basename(path) or path,
                                       path=path, language=_language_for(path), code=_clip(content))

        elif name == "run_shell":
            state_bus.publish_activity("tool_call", str(args.get("command", ""))[:300], tool=name)

        else:
            # find_project, search_web, etc. — a compact breadcrumb.
            detail = args.get("query") or args.get("project") or args.get("name") or ""
            state_bus.publish_activity("tool_call", f"{name} {detail}".strip(), tool=name)
    except Exception:
        pass


def _read_payload(name: str, args: dict, result) -> tuple[str, str]:
    """Extract (path, code) from a read tool's result."""
    if name == "read_project_file" and isinstance(result, str):
        # Format: "File: <path> (project: X)\n\n<content>"
        first, _, body = result.partition("\n\n")
        m = _FILE_HEADER_RE.match(first)
        if m:
            return m.group(1), body
        return args.get("filename", ""), result
    return args.get("path", ""), (result if isinstance(result, str) else "")


# ── spoken vs displayed ──────────────────────────────────────────────────────

_CODE_FENCE_RE = re.compile(r"```")
_SPEAK_FULL_MAX = int(os.getenv("FRIDAY_SPEAK_FULL_MAX", "320"))


def is_rich_reply(text: str) -> bool:
    """True if the reply is code/review/doc-like — long, fenced, or list-heavy —
    and so should be SHOWN in the window, not read out in full."""
    if not text:
        return False
    if _CODE_FENCE_RE.search(text):
        return True
    if len(text) > _SPEAK_FULL_MAX:
        return True
    # multiple markdown list items / headings = structured doc, not a chat line
    return len(re.findall(r"(?m)^\s*(?:[-*]\s+|\d+[.)]\s+|#{1,6}\s+)", text)) >= 3


def spoken_gist(text: str) -> str:
    """A short spoken stand-in for a rich reply: the opening line(s) + a pointer
    to the screen. Strips markdown so nothing syntax-y is read aloud."""
    plain = re.sub(r"[`*#>]+", "", text).strip()
    # first 1–2 sentences, capped
    sentences = re.split(r"(?<=[.!?])\s+", plain)
    gist, n = "", 0
    for s in sentences:
        if not s.strip():
            continue
        gist = f"{gist} {s}".strip()
        n += 1
        if len(gist) >= 200 or n >= 2:
            break
    return f"{gist} The full details are on your screen, Sir.".strip()


def deliver_reply(text: str, speak) -> None:
    """Publish a final answer for DISPLAY (full text + assistant_message activity),
    and SPEAK either the whole thing (short chat) or a short gist (rich content).
    `speak` is the caller's enqueue_speech."""
    text = (text or "").strip()
    if not text:
        return
    state_bus.publish_activity("assistant_message", text)
    speak(spoken_gist(text) if is_rich_reply(text) else text)
