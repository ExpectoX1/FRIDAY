# FRIDAY Coding Window — Backend → Swift Contract (for Codex)

The backend half of the coding-window upgrade is **done and live**. This is the
contract your `FridayControlWindowView` renders against. **No backend changes
needed from you** — build the Swift window against the events below.

Lane reminder: backend (`state_bus`, tools, activity emission) is Claude's; the
Swift window rendering is yours. The WS `activity` shape below is the handshake —
please don't edit `backend/` to change it; ping for contract changes.

---

## Transport (unchanged endpoint)

`WS 127.0.0.1:8767/ws/state` — same socket you already use.

Every message is a JSON object with the **existing** state fields **plus** a new
`activity` array. All existing fields are unchanged and backward-compatible:

```json
{
  "state": "tool_running",          // idle|listening|transcribing|thinking|tool_running|speaking|approval_required|error
  "outcome": "neutral",             // success|error|neutral
  "message": "Read main.py",
  "transcript": "review my teenyurl code",
  "replyPreview": "<full reply text>",   // now the FULL reply (not capped)
  "tool": "read_project_file",
  "requiresApproval": false,
  "pendingCommand": null,
  "activity": [ /* Event objects — see below */ ]
}
```

### How to consume `activity`
- **On connect:** the first message's `activity` is the **full history** (up to 80
  events) — seed your timeline with it.
- **After that:** each message carries only the **new** event(s) in `activity`
  (usually 0 or 1). **Append** them to your timeline; **dedup by `id`**.
- `state`/`message`/etc. update the header on every message as before. A
  state-only update sends `activity: []`.

---

## Event object

```json
{
  "id": "a1b2c3d4e5f6",   // unique — dedup on this
  "ts": 1782600000.12,    // epoch seconds
  "kind": "code_snippet", // see kinds below
  "text": "main.py",      // short human label for the row/card
  "path": "/Users/.../teenyurl/main.py",  // optional
  "language": "python",   // optional (for code_snippet/file_*): python|swift|javascript|...
  "code": "from fastapi import FastAPI\n...",  // optional, may be truncated for display
  "diff": null,           // optional (reserved for v2 write diffs)
  "tool": "read_project_file"  // optional — which tool produced it
}
```

Only the fields relevant to a kind are present (e.g. a `code_snippet` has
`code`+`language`+`path`; a `tool_call` has just `text`+`tool`).

### Event kinds → suggested card
| kind | when | render as |
|---|---|---|
| `user_message` | user's turn (voice or typed) | right-aligned chat bubble (`text`) |
| `assistant_message` | FRIDAY's full reply | left-aligned chat bubble (`text`, markdown ok) |
| `status` | progress note | compact dim step row |
| `tool_call` | ran a tool (run_shell/find_project/search) | compact step row (`text`, `tool`) |
| `file_read` | read a file | file card header: filename (`text`) + `path` |
| `code_snippet` | file/code contents | **monospace code block**, `language`, copy button, `path` |
| `file_write` | wrote a file | file card "Wrote …" + `path` |
| `diff` | (v2) before/after | diff card with +/- coloring (`diff`) |
| `approval` | shell/destructive pending | **approval card** (`text` = command) + Approve/Deny → existing `POST /api/approval` |
| `error` | a tool failed | red error row (`text`) |

A typical "review my teenyurl code" turn streams:
`user_message` → `tool_call`(find_project) → `file_read` → `code_snippet` →
`assistant_message`.

---

## Header ("current work")
Drive it from the top-level `state` (unchanged enum): idle / listening /
transcribing / thinking / tool_running / speaking / approval_required / error.
Use `message` for the one-line detail ("Reading main.py"). Add your dot/waveform.

## Voice behavior you can rely on (already handled backend-side)
- FRIDAY **no longer reads code/reviews/docs aloud** — she speaks a short gist and
  the full text arrives as `assistant_message` + `code_snippet`. So the window is
  the source of truth for full content; the voice is just the gist.
- `replyPreview` now carries the **full** reply text (handy if you want it before
  the `assistant_message` event).

## Approvals (unchanged)
Shell/destructive actions still set `state:"approval_required"` +
`requiresApproval`/`pendingCommand`, and now also emit an `approval` activity
event. Approve/Deny via the existing `POST /api/approval {"approved": true|false}`.

## Not in v1 (don't build yet)
- `diff` cards (writes currently emit `file_write` + a `code_snippet` of the new
  content; before/after diffs come in v2 with a `replace_in_file` tool).
- File tree / IDE tabs.

## Quick test against a live backend
1. `cd backend && python main.py`
2. Connect to `ws://127.0.0.1:8767/ws/state`, log every message.
3. Say *"review the main.py in my teenyurl project"* — you should see
   `user_message`, `file_read`, `code_snippet` (with the python source), then
   `assistant_message` (the review), while the terminal/voice only gives the gist.
