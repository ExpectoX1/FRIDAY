# Mid-task course correction — design (not yet built)

**Goal:** let the user redirect a running agent task by voice — "no, the *other*
folder", "stop, wrong project", "actually make it a zip" — instead of waiting
for the task to finish (or fail) and then undoing it.

## Why it's impossible today

`assistant_loop` is strictly turn-based: `run_agent()` is awaited inline, so the
mic does not open again until the whole multi-step task has completed. While the
agent works, user speech has nowhere to go. Barge-in (`barge_in_monitor`) only
interrupts *TTS playback* — it stops FRIDAY talking, not FRIDAY working.

The one existing correction hook is *post-hoc*: session history lets a follow-up
turn say "undo that", and the confirmation flow lets the user block a RISKY
command before it runs. Neither helps once a wrong-but-SAFE step sequence is in
flight (e.g. organizing the wrong folder with confirmed steps).

## Design

### 1. Agent runs as a cancellable task

```
agent_task = asyncio.create_task(run_agent(goal, ...))
```

The loop then `await`s a race between `agent_task` and a *correction listener*.
The agent's tool executions already hop threads via `asyncio.to_thread`, so the
event loop stays free to listen.

### 2. Listening while working (the hard part on this hardware)

The mic is contended: TTS may speak progress lines while tools run, and laptop
speakers bleed into the mic (the reason barge-in defaults OFF). Constraints:

- Reuse the barge-in gating: while `is_speaking` is set, require the *elevated*
  volume-scaled threshold; between speech, use the normal STT threshold.
- Feed captured audio through the existing `transcribe()`; discard self-echo
  with `_is_self_echo` exactly like the main loop.
- Typed input (`POST /api/input`) needs none of this — the island text box is
  the *reliable* correction channel and should ship first (Phase A below).

### 3. Injecting the correction

A correction does **not** kill the agent; it lands as a user message in the
agent's own conversation:

```
messages.append({"role": "user", "content":
    f"COURSE CORRECTION from the user: '{heard}'. Re-read the goal in light of "
    "this. If a prior step acted on the wrong target, undo or redo it as "
    "needed, then continue."})
```

Mechanically: `run_agent` gains a `correction_queue` (thread-safe). The loop
drains it at the top of every iteration, *before* calling the brain. A step
already executing finishes (tools are not preemptible — killing a half-run
script is worse than one extra step); the correction applies from the next
brain call.

Cancellation stays available as the blunt form: "stop" / "cancel" cancels
`agent_task` outright (checked against the same DENIAL_PHRASES used for
confirmations).

### 4. State bus

New activity kind `correction` + a `correcting` flag on the state event so the
island can show "Adjusting course…". Additive, per the bridge contract.

## Phasing

- **Phase A (cheap, reliable):** corrections via typed input only. The island
  already posts to `/api/input`; while an agent task runs, route those lines
  into `correction_queue` instead of the next-turn queue. No audio contention
  at all. Ship this first; it proves the injection mechanics.
- **Phase B:** voice corrections with headphones (`FRIDAY_BARGE_IN=1` reused as
  the gate), using the elevated threshold + self-echo filter.
- **Phase C (only if B works in practice):** speaker-mode voice corrections —
  needs real echo cancellation (e.g. macOS voice-processing audio unit), which
  is its own project.

## Test plan

- `test_regression.py`: correction-queue drain order (pure: corrections land
  before the next brain call, "stop" cancels), DENIAL_PHRASES reuse.
- `test_capabilities.py`: scripted agent task in the sandbox + a mid-task
  correction injected after step 1; assert the final state reflects the
  corrected target, not the original.
