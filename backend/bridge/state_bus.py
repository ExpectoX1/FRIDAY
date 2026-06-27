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
import copy
import threading

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
    _broadcast(snapshot)


def get_state() -> dict:
    with _lock:
        return copy.deepcopy(_state)


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
