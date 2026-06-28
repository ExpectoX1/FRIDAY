# FRIDAY Island Bridge

Local bridge between the Python backend and the SwiftUI notch-island app.
Runs in `main.py`'s process on **`127.0.0.1:8767`** (separate from the graph
viz on 8766). Purely additive — the voice app runs identically whether or not
the island is connected.

## WebSocket — `ws://127.0.0.1:8767/ws/state`
On connect you get the current snapshot, then one message per state change.
The event is **factual**; the Swift UI maps it to expressions/moods.

```json
{
  "state": "speaking",
  "outcome": "neutral",
  "message": "Speaking...",
  "transcript": "open spotify and play...",
  "replyPreview": "On it, Sir.",
  "tool": null,
  "requiresApproval": false,
  "pendingCommand": null
}
```

`state` ∈ `idle | listening | transcribing | thinking | tool_running |
speaking | approval_required | error`
`outcome` ∈ `success | error | neutral`
`tool` = tool name during `tool_running` (else null).
`replyPreview` = text being spoken (during `speaking`).
During `approval_required`: `requiresApproval=true`, `pendingCommand` = the command.

## HTTP
- `GET  /api/health` → `{"status":"ok","state":"idle"}`
- `POST /api/approval` `{"approved": true|false}` → resumes/cancels the pending
  confirmation (same hook as voice "yes/no" and the menu bar).
- `POST /api/input` `{"text":"..."}` → ✅ live. Injects a typed command into the
  same routing the voice loop uses (returns `{"ok":true}`). The loop takes the
  next turn from typed input instead of the mic. A typed command queued while
  FRIDAY is speaking runs once she finishes.

## Notes
- `mood` is intentionally NOT sent — the UI derives expression/mood from `state`.
- `amplitude` is reserved for future audio-reactive speech animation.
