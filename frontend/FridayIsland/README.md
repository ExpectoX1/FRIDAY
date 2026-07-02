# FRIDAY Island

Native macOS notch island for FRIDAY, built with SwiftUI and AppKit.

## Run

```sh
cd frontend/FridayIsland
swift run FridayIsland
```

Start the Python backend with `python main.py` to use the live bridge at
`127.0.0.1:8767`. If the bridge is unavailable (or drops — e.g. a backend
restart), the app shows an honest offline state and reconnects automatically
with backoff; the island face sleeps until the backend is back.

For UI development without a backend, launch with `FRIDAY_ISLAND_MOCK=1` to
play a simulated timeline that cycles through every visual state. Mock is
opt-in only — it never appears as a runtime fallback.

## Backend Contract

WebSocket:

```text
ws://127.0.0.1:8767/ws/state
```

Example event:

```json
{
  "state": "speaking",
  "outcome": "success",
  "message": "Answering...",
  "transcript": "open spotify and play...",
  "replyPreview": "On it, Sir.",
  "tool": null,
  "requiresApproval": false,
  "pendingCommand": null,
  "amplitude": null
}
```

HTTP:

```text
GET  /api/health
POST /api/approval  { "approved": true }
POST /api/input     { "text": "play something calm" }
```

The backend should stay factual. The app maps state to expression/mood locally.
Typed input is enabled whenever the connection is live; while offline it is
disabled with an explanatory note and re-enables itself on reconnect.

Forward compatibility: unknown activity `kind`s render as plain status rows and
malformed frames are skipped — additive backend changes never break the client.

## Optional Frame Animations

The face has a SwiftUI procedural fallback for every FRIDAY state. It can also
play bundled 128x64 bitmap animation JSON files when they are present:

```text
frontend/FridayIsland/Sources/FridayIsland/Resources/Animations/idle01.json
frontend/FridayIsland/Sources/FridayIsland/Resources/Animations/love01.json
```

Those files are intentionally not vendored until their license/permission is
clear. Once added, idle uses `idle01`; happy speaking uses `love01`.
