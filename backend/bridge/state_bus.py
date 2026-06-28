"""Thread-safe assistant-state bus for the FRIDAY Island frontend.

The voice loop (and agent loop) call set_state() from their own threads; the
WebSocket server (running in its own thread/event loop) subscribes and pushes
every change to connected clients. The bus is the single source of truth and is
completely decoupled from transport — if nothing is connected, set_state() is a
cheap no-op beyond updating the snapshot.

Contract (one factual event; the Swift UI maps it to expressions/moods):
    state:           idle | listening | transcribing | thinking |
                     tool_running | speaking | approval_required | error
    outcome:         success | error | neutral
    message:         short human status line
    transcript:      the user's last utterance
    replyPreview:    text FRIDAY is about to speak (during `speaking`)
    tool:            tool name (during `tool_running`) or null
    requiresApproval/pendingCommand: set during `approval_required`
"""
import collections
import copy
import threading
import time
import uuid

_lock = threading.Lock()

_state = {
    "state": "idle",
    "outcome": "neutral",
    "message": "",
    "transcript": "",
    "replyPreview": "",
    "tool": None,
    "requiresApproval": False,
    "pendingCommand": None,
}

# Structured activity timeline for the coding window. Each broadcast carries the
# NEW event(s) in `activity` (clients append, dedup by id); set_state carries an
# empty `activity`. On connect the server sends the whole log so late joiners
# catch up. Capped so memory/bandwidth stay bounded.
_ACTIVITY_MAX = 80
_activity = collections.deque(maxlen=_ACTIVITY_MAX)

# Event kinds the UI knows how to render.
ACTIVITY_KINDS = {
    "user_message", "assistant_message", "status", "tool_call",
    "file_read", "file_write", "code_snippet", "diff", "approval", "error",
}

# Each subscriber is (event_loop, asyncio.Queue) owned by a WS connection.
_subscribers: list = []


def set_state(state: str | None = None, **fields) -> None:
    """Update the current state and broadcast it. Safe to call from any thread."""
    with _lock:
        if state is not None:
            _state["state"] = state
        for key, value in fields.items():
            _state[key] = value
        snapshot = copy.deepcopy(_state)
        snapshot["activity"] = []  # state-only update — no new activity events
    _broadcast(snapshot)


def publish_activity(kind: str, text: str = "", *, state: str | None = None,
                     outcome: str | None = None, path: str | None = None,
                     language: str | None = None, code: str | None = None,
                     diff: str | None = None, tool: str | None = None) -> dict:
    """Append a structured activity event and broadcast it to the window.

    Optionally also flips the live `state`/`outcome` (so e.g. a file_read can set
    state='tool_running' in the same call). Safe to call from any thread.
    """
    event = {"id": uuid.uuid4().hex[:12], "ts": time.time(), "kind": kind, "text": text or ""}
    for key, value in (("path", path), ("language", language), ("code", code),
                       ("diff", diff), ("tool", tool)):
        if value is not None:
            event[key] = value

    with _lock:
        _activity.append(event)
        if state is not None:
            _state["state"] = state
        if outcome is not None:
            _state["outcome"] = outcome
        if text and state is not None:
            _state["message"] = text
        snapshot = copy.deepcopy(_state)
        snapshot["activity"] = [event]
    _broadcast(snapshot)
    return event


def get_state() -> dict:
    with _lock:
        return copy.deepcopy(_state)


def get_activity() -> list:
    with _lock:
        return list(_activity)


def subscribe(loop, queue) -> None:
    with _lock:
        _subscribers.append((loop, queue))


def unsubscribe(queue) -> None:
    with _lock:
        _subscribers[:] = [(l, q) for (l, q) in _subscribers if q is not queue]


def _broadcast(snapshot: dict) -> None:
    for loop, queue in list(_subscribers):
        try:
            loop.call_soon_threadsafe(queue.put_nowait, snapshot)
        except Exception:
            pass
