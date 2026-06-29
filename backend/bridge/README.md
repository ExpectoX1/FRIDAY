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
  "pendingCommand": null,
  "brain": "local",
  "streamingReply": ""
}
```

`state` ∈ `idle | listening | transcribing | thinking | tool_running |
speaking | approval_required | error`
`outcome` ∈ `success | error | neutral`
`tool` = tool name during `tool_running` (else null).
`replyPreview` = text being spoken (during `speaking`).
During `approval_required`: `requiresApproval=true`, `pendingCommand` = the command.
`brain` ∈ `local | cloud` — which brain is handling the turn. `cloud` when
`FRIDAY_BRAIN=cloud` (whole brain on Groq) or while a deep code follow-up is
transiently routed to the cloud. The UI shows a "Cloud" badge when `cloud`.
`streamingReply` = the assistant's reply SO FAR, updated token-by-token while a
reply is generating, `""` when idle. Lets the UI render a live streaming bubble.
On completion the backend clears it to `""` and sends the full text as an
`assistant_message` activity, so the persisted bubble is unchanged. Additive —
old clients ignore it. (Currently emitted for single-shot conversational replies;
tool-summarized and agent replies still arrive only as the final activity.)

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
