# FRIDAY — Project Guide (for Claude)

Local, voice-driven personal AI assistant for macOS. Runs on-device via Ollama.
Mic → STT → LLM (native tool calling) → tools → TTS, with a Neo4j memory graph
and a SwiftUI "notch island" frontend. Working dir for runtime: `backend/`.

## Current stack (as of this snapshot — supersedes CODEBASE_CONTEXT.txt where they differ)
- **Brain** (chat + agent loop): `qwen3:14b` via Ollama, **always with `think=False`**
  (Qwen3 otherwise runs chain-of-thought before every tool call ≈ 9s; off ≈ 1.2s).
  Override: `FRIDAY_LOCAL_MODEL`. Cloud A/B: `FRIDAY_BRAIN=cloud` → Groq gpt-oss-20b
  (key `GROQ_API` in `backend/.env`). gemma3 can't do native tools; don't use it as brain.
- **Memory reasoner**: shares `qwen3:14b` (one big model resident — avoids VRAM thrash).
- **Router** (is_complex SIMPLE/COMPLEX): `qwen2.5:3b`.
- **Vision** (`look_at_screen` tool): `qwen2.5vl:3b` (~1s warm).
- **STT**: faster-distil-whisper-small.en (adaptive threshold, pre-roll, abortable).
- **TTS**: Kokoro (af_heart), persistent output stream, sentence-streamed.
- Hardware: 24GB M4 Pro — below Ollama's 32GB MLX threshold (uses llama.cpp Metal).

## How to run
```
cd backend && python main.py            # local brain (default)
FRIDAY_BRAIN=cloud python main.py        # cloud brain (Groq)
```
Requires Ollama running (`ollama serve`); Neo4j for memory (`neo4j start`, bolt://localhost:7687, pass friday123).

## How to TEST (do this instead of manual voice testing — the user finds that exhausting)
```
cd backend && python test_regression.py     # routing + tool selection + continuity (~30s, exits nonzero on fail)
cd backend && python test_conversations.py   # MULTI-TURN sessions through the real pipeline (~40s) — every live
                                             # bug so far was a between-turns seam bug; this catches them in CI
cd backend && python test_capabilities.py    # real end-to-end agent tasks in a sandbox (per brain)
cd backend && python bench_brain.py          # latency + tool-accuracy across models
cd backend && python bench_router.py         # raw qwen2.5:3b router vs labeled routing cases
```
Add a new assertion to `test_regression.py` whenever a bug is found, rather than re-catching it by voice.

## Architecture notes
- **Native tool calling** everywhere (no JSON-in-text). `brain/llm.py` `_call_brain` is the
  backend-agnostic core; `chat()`/`agent_chat()` + their `_stream` variants build on it.
- **Routing**: `is_complex()` keyword heuristic → qwen2.5:3b fallback. COMPLEX_SIGNALS (incl.
  stream/video/live) route to the agent; SIMPLE_SIGNALS (play/open/chitchat) stay single-shot.
  Every decision is logged to `~/FRIDAY/logs/routing.jsonl` with the deciding tier — that's the
  dataset for future routing work. Benchmarked (bench_router.py): the raw 3b router is only
  ~65% on the labeled cases (proactive watch/remind intents fail hardest) and enriching its
  rubric made it WORSE — the pins are the mechanism at this model size, not debt to remove.
- **Agent loop** (`brain/agent.py`): native message-passing, confirmation→resume for RISKY
  commands, dup-call guard, terminal-tool short-circuit, and a "don't claim done after a failed
  step" push-back.
- **Continuity**: `set_last_result()` + `_referential_open()` resolve "open it / the chords" to
  the last result's URL deterministically.
- **Safety**: `sandbox/executor.py` blocks shell metachars / dangerous cmds; RISKY cmds need
  confirmation. The agent writes Python scripts to `~/FRIDAY/workspace/` for batch file ops.
- **Confirmation** resolves identically via voice ("yes"/"no", punctuation-proof), the rumps
  menu bar, and the island — all call `approve_pending()`/`deny_pending()`.

## Frontend / bridge (Phase 8 — in progress; Codex owns the Swift app)
- **Lane split**: Claude = `backend/`. Codex = `frontend/FridayIsland/` (SwiftUI notch island).
  Don't edit each other's lane; contract changes go through the bridge.
- **Bridge** (`backend/bridge/`, additive, on `127.0.0.1:8767`; graph viz is separate on 8766):
  - `WS /ws/state` — factual state events (UI derives mood/expression). See `bridge/README.md`.
  - `GET /api/health`, `POST /api/approval`, `POST /api/input` (typed cmds → voice loop) — all live.
  - States emitted: idle/listening/transcribing/thinking/tool_running/speaking/approval_required/error.

## What's left (backend)
1. **Phase 5 — Proactive**: timers/reminders + background scheduler + trigger registry. (top rec)
2. **Phase 7 — voices**: optional Kokoro → Fish Audio (Irish voice).
3. **Phase 6 — vision ReAct**: screenshot → reason → act via mac_core AX layer.
4. Debt: false-success detection (script runs but misses goal); qwen2.5:3b router flakiness;
   `keep_alive=30m` keeps ~10GB resident (memory pressure on 24GB — consider env-tunable).

## Working style
- Don't over-tackle every bug found in testing — the user gets fatigued by the churn. Prefer
  data-driven decisions (benchmarks/tests) and architectural fixes over per-case prompt tweaks.
- Commit when work is verified; the repo has been pushing the local branch to remote `main`.
- End commits with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
