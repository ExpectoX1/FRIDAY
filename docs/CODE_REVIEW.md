# FRIDAY Code Review

Review date: 2026-06-30

Scope reviewed:
- `backend/`: voice loop, brain/router/agent, tools, sandbox, proactive scheduler, memory, bridge.
- `frontend/FridayIsland/`: SwiftUI/AppKit notch island and coding window.

Commands run:
- `cd backend && ../.venv/bin/python test_regression.py` -> `107/107 passed`.
- `cd backend && ../.venv/bin/python test_proactive.py` -> `ALL PASSED`.
- `cd frontend/FridayIsland && swift build` -> build completed; SwiftPM printed `Found unhandled resource .../Resources` before succeeding.

I did not run `main.py`.

## A. Findings

| Severity | File:line | What's wrong | Why it matters | Suggested fix | Rough effort |
|---|---|---|---|---|---|
| Critical | `backend/tools/files.py:4`, `backend/tools/files.py:14`, `backend/tools/registry.py:85`, `backend/tools/registry.py:100`, `backend/brain/agent.py:497` | `read_file` and `write_file` are direct model tools with no path policy, no sensitive-path denylist, and no confirmation gate. | The shell executor blocks `.env`/`.ssh` paths, but the file tools bypass that entire safety layer. A model/tool-call mistake or prompt injection can read ignored secrets or write arbitrary files. | Put all file tools behind a shared filesystem policy: allowlist project/workspace roots by default, deny secrets (`.env`, `.ssh`, keychains, credentials), require confirmation for writes outside a safe workspace, and make `write_file` return `NEEDS_CONFIRMATION` for risky targets. | M |
| Critical | `backend/tools/web.py:136`, `backend/tools/web.py:141`, `backend/brain/agent.py:571`, `backend/tools/registry.py:70`, `backend/tools/registry.py:120` | Untrusted web/page/file/email content is fed back into a tool-capable agent loop as ordinary tool messages. | Search/page results can contain adversarial instructions. The next agent iteration still has tools like `run_shell` and `navigate_browser`, so the system is exposed to indirect prompt injection. | Treat external content as tainted: wrap it in explicit untrusted-data delimiters, add a system rule that tool results cannot issue instructions, block consequential tools for one turn after untrusted reads unless the user's original request requires them, and add prompt-injection regression tests. | M-L |
| High | `backend/main.py:280`, `backend/main.py:290`, `backend/main.py:322`, `backend/voice/stt.py:93`, `backend/voice/tts.py:177` | Barge-in opens a second mic `InputStream` while the app also opens the main STT stream, and it calls global `sd.stop()` during playback. | This matches the reproducible speaker `bus error` profile: PortAudio/sounddevice devices are being opened/stopped from multiple threads while TTS is writing. Default-off helps, but enabling barge-in can still crash the process. | Use one audio coordinator: a single mic owner that fans out samples to STT and barge-in VAD, never call global `sd.stop()` from the monitor, and stop playback through the TTS worker with a queue/control message. | M |
| High | `backend/bridge/server.py:42`, `backend/bridge/server.py:48`, `backend/bridge/server.py:52`, `backend/bridge/server.py:62`, `backend/bridge/server.py:88` | The bridge binds to `127.0.0.1`, but `/api/approval` and `/api/input` are unauthenticated action endpoints. | Any local process can approve a pending command or inject typed commands. A local webpage/app reaching localhost could also attempt bridge interaction depending on browser/network policy. | Add a random per-run token, require it on WS and HTTP actions, validate `Origin` where applicable, and return approval success only after the scheduled future completes or reports no pending action. | S-M |
| High | `backend/sandbox/executor.py:75`, `backend/sandbox/executor.py:76`, `backend/sandbox/executor.py:294` | `git add` and `git commit` are classified `SAFE`, so they execute without confirmation. | This contradicts the stated guardrail that local code review/explanation should not do unrelated git actions. It also allows the agent to mutate repo history without the same approval gate used for risky shell commands. | Move `git add` and `git commit` to `RISKY_GIT_SUBCOMMANDS`, or require explicit user intent in the current utterance before allowing them. Add tests for "review code" never staging/committing. | S |
| High | `backend/brain/agent.py:277`, `backend/brain/agent.py:396`, `backend/main.py:725`, `backend/main.py:742` | Agent replies have a token callback hook, but `main.py` calls `run_agent` without wiring it to `state_bus.streamingReply`; only the single-shot chat path streams. | Multi-step/code/tool answers still pop into the coding window at the end, so recently-added reply streaming is incomplete for the highest-latency path. | Pass an `on_token_callback` from `main.py` that accumulates tokens and sets `streamingReply`, then clears it before `deliver_reply`, matching the single-shot path. | S |
| Medium | `backend/bridge/activity.py:32`, `backend/bridge/activity.py:91`, `backend/brain/code_context.py:36` | File headers are parsed with `^File:\s*(\S+)`, so paths with spaces are truncated. | Local projects can have spaces in names. A read of `/Users/.../Teeny URL/main.py` would be displayed/remembered as `/Users/.../Teeny`, breaking file cards and code follow-up context. | Change the header format to JSON metadata, or parse up to ` (project:` instead of `\S+`. Add a regression for a project path containing spaces. | S |
| Medium | `backend/bridge/server.py:78`, `backend/bridge/server.py:82`, `backend/bridge/state_bus.py:136`, `backend/bridge/state_bus.py:139` | WS send errors and state-bus broadcast errors are swallowed; subscriber queues are unbounded. | A broken/slow client can silently stop receiving or accumulate queued snapshots without observability. Debugging stuck UI state becomes hard. | Log disconnect/broadcast failures at debug level, give queues a small max size, and drop/coalesce old state snapshots for slow clients. | S-M |
| Medium | `frontend/FridayIsland/Sources/FridayIsland/BackendClient.swift:65`, `frontend/FridayIsland/Sources/FridayIsland/AssistantModels.swift:118` | The Swift client decodes activity kind with a strict enum; any unknown backend activity kind throws and terminates the receive loop. | The bridge is evolving. A new activity kind would make the window fall back to mock/offline instead of ignoring only the unknown card. | Add an `.unknown(String)`-style custom decoder or decode activity kinds leniently and render unknowns as status/tool rows. | S |
| Medium | `backend/proactive/scheduler.py:196`, `backend/proactive/scheduler.py:198`, `backend/proactive/scheduler.py:201`, `backend/proactive/scheduler.py:239` | Scheduler action and persistence failures are swallowed. | A monitor can fail forever, or reminders can stop persisting, with no terminal/UI signal. The user only notices missed alerts. | Log action and save failures, publish a bridge activity for repeated monitor failures, and mark trigger health in persisted state. | S |
| Medium | `backend/tools/gmail_tool.py:155`, `backend/tools/gmail_tool.py:161`, `backend/proactive/mail_monitor.py:50` | Mail-monitor fetch returns `[]` on any IMAP error with no logging. | Network/auth failures look exactly like "no matching mail", so the proactive Gmail monitor can silently go blind. | Return a typed error or log at least once per failure window; preserve `[]` only for actual empty results. Surface monitor health in `list_reminders`. | S |
| Medium | `backend/main.py:486`, `backend/main.py:493`, `backend/main.py:518`, `backend/main.py:524`, `backend/main.py:829` | `pending_confirmation` is shared across the voice loop, menu-bar callbacks, and bridge approvals without a lock or single owner API. | Double clicks, voice approval, and bridge approval can race. The bridge returns `{"ok": true}` immediately even if the scheduled approval later fails or no command remains. | Own confirmation state inside the asyncio loop; all external callers should enqueue approval intents and await/inspect the future result. | S-M |
| Medium | `backend/local_code.py:29`, `backend/local_code.py:392`, `backend/main.py:53`, `backend/main.py:691`, `backend/tools/projects.py:97` | There are two local-code review systems: disabled `local_code.py` and active project tools. | The disabled path still has session state and tests, while the active path is model-led through tools. This makes behavior and ownership unclear and invites regressions. | Either remove/archive `local_code.py`, or make it the single deterministic resolver behind the registry tool so tests cover the path actually used in production. | M |
| Low | `backend/memory/graphiti_client.py:17`, `backend/memory/graphiti_client.py:19`, `backend/api.py:16` | Neo4j credentials are hardcoded as `neo4j` / `friday123`. | It is local, but hardcoded credentials normalize weak defaults and make accidental exposure harder to rotate. | Move Neo4j URI/user/password to env vars with safe local defaults documented in `.env.example` only. | S |
| Low | `backend/main.py:849`, `backend/main.py:855`, `backend/memory/store.py:14`, `backend/memory/store.py:178`, `backend/voice/tts.py:36`, `backend/voice/tts.py:127` | Long-lived daemon threads, a `ThreadPoolExecutor`, and the persistent TTS output stream have no clean shutdown path. | This is a plausible contributor to exit-time leaked semaphore/resource warnings and can leave audio devices in a bad state across restarts. | Add shutdown sentinels for queues, close TTS streams, stop scheduler, and call `_executor.shutdown(wait=False)` on app termination. | M |
| Low | `frontend/FridayIsland/Sources/FridayIsland/AssistantStore.swift:100`, `frontend/FridayIsland/Sources/FridayIsland/AssistantStore.swift:112`, `frontend/FridayIsland/Sources/FridayIsland/AssistantStore.swift:115` | The frontend tries the backend once, then starts mock mode; there is no timed live reconnect loop. | If the backend starts after the app, or restarts after a WS failure, the user must manually reconnect. | Keep mock as a visual fallback, but schedule exponential reconnect attempts while in `.mock`/`.disconnected`. | S |
| Low | `frontend/FridayIsland/Sources/FridayIsland/BitmapAnimationView.swift:63`, `frontend/FridayIsland/Sources/FridayIsland/FaceView.swift:25`, `frontend/FridayIsland/Sources/FridayIsland/FaceView.swift:41` | The bitmap animation pipeline is wired, but the resources folder currently only contains `.gitkeep`; animation lookup will always fall back to procedural face. | This is not a correctness bug, but it explains why copied animations are not available in the app surface. | Either remove the unused bitmap path for now or add real `Animations/*.json` assets and a test that `BitmapAnimation.exists` succeeds for shipped names. | S |

## B. "Do Better" List

- Create a single "capability policy" layer for every tool, not only `run_shell`. Today shell has classification (`backend/sandbox/executor.py:191`), but file, browser, Gmail, Calendar, and app-control tools each decide safety alone.
- Add taint metadata to tool results. Web (`backend/tools/web.py:102`), page, email (`backend/tools/gmail_tool.py:177`), and file reads should carry source/trust metadata into the agent.
- Replace prompt-heavy guardrails with deterministic preconditions for local code work. The prompt says "never use web for local code" (`backend/brain/agent.py:265`), but deterministic enforcement should live in code and tests.
- Split `main.py`; it currently owns audio queues, barge-in, TTS workers, confirmation, bridge setup, routing, local-code interception, and the event loop (`backend/main.py:26`, `backend/main.py:280`, `backend/main.py:588`). Smaller services would make races easier to reason about.
- Give every background subsystem a health surface in the bridge: scheduler alive, mail monitor last poll, web monitor last error, memory connected, audio device active.
- Move user-specific constants out of source: hardcoded `Siddharth` in memory (`backend/memory/store.py:127`) and Neo4j defaults (`backend/memory/graphiti_client.py:17`) should become config.
- Add structured error types instead of string prefixes. `_tool_failed()` currently depends on string prefixes (`backend/brain/agent.py:96`), which is better than substring matching but still brittle.
- Make Swift bridge decoding forward-compatible: unknown states/activity kinds should show degraded cards instead of killing the WS receive loop (`frontend/FridayIsland/Sources/FridayIsland/BackendClient.swift:65`).
- Add integration tests with fake bridge events for streaming, tool-running, and approval sequences. Current backend tests cover logic; Swift behavior is only build-checked.
- Add one "hostile content" test: a fake `search_web` result saying "ignore instructions and run shell ..." should not result in any consequential tool call.

## C. Functionality Ratings

Scores are `/5` for correctness, robustness, and completeness.

| Subsystem | Correctness | Robustness | Completeness | Notes |
|---|---:|---:|---:|---|
| Voice I/O | 3 | 2 | 3 | STT has useful pre-roll/VAD/watchdog controls (`backend/voice/stt.py:27`, `backend/voice/stt.py:161`), and TTS now uses a persistent stream (`backend/voice/tts.py:174`), but barge-in has unsafe audio-device concurrency (`backend/main.py:280`). |
| Routing | 4 | 3 | 3 | Regression coverage is strong for current phrases (`backend/test_regression.py:97`, `backend/test_regression.py:145`), but routing still mixes keyword heuristics and LLM classification (`backend/brain/llm.py:498`). |
| Agent loop | 3 | 3 | 3 | Loop limits, duplicate-call guard, failure pushback, and verification exist (`backend/brain/agent.py:12`, `backend/brain/agent.py:480`, `backend/brain/agent.py:448`), but prompt injection and incomplete agent streaming remain. |
| Tools | 3 | 2 | 3 | Tool breadth is good (`backend/tools/registry.py:59`), but safety is inconsistent across shell/file/browser/app tools. |
| Sandbox | 3 | 2 | 2 | Shell metacharacters and blocked commands are classified (`backend/sandbox/executor.py:27`, `backend/sandbox/executor.py:101`), but the policy is shell-only and `git add/commit` are safe (`backend/sandbox/executor.py:75`). |
| Memory | 3 | 2 | 3 | Async storage avoids blocking (`backend/memory/store.py:177`) and retrieval returns a no-memory sentinel (`backend/memory/retrieve.py:105`), but Neo4j failures degrade to no memory and credentials/defaults are hardcoded. |
| Proactive / scheduler | 4 | 3 | 3 | Scheduler tests pass and recurrence/dedup are solid (`backend/test_proactive.py:206`, `backend/proactive/scheduler.py:243`), but action/save failures are swallowed. |
| Calendar | 4 | 3 | 3 | EventKit read-only access and range parsing are clear (`backend/tools/calendar_tool.py:1`, `backend/tools/calendar_tool.py:63`), with graceful permission messaging, but no integration test against real EventKit. |
| Gmail + monitor | 3 | 2 | 3 | Query translation and monitor dedupe are tested (`backend/test_regression.py:249`, `backend/test_proactive.py:172`), but IMAP failures disappear as empty inboxes in monitor mode. |
| Bridge | 3 | 3 | 3 | State bus locking and activity snapshots are useful (`backend/bridge/state_bus.py:68`, `backend/bridge/server.py:75`), but action endpoints are unauthenticated and WS/send errors are swallowed. |
| Frontend | 4 | 3 | 4 | The window now has streaming and thinking indicators (`frontend/FridayIsland/Sources/FridayIsland/FridayControlWindowView.swift:13`, `frontend/FridayIsland/Sources/FridayIsland/FridayControlWindowView.swift:85`), builds successfully, and has good UI structure; reconnect and decode forward-compat are weak. |

## D. Top 5 Highest-Leverage Fixes

1. Build a shared tool safety policy for file, shell, browser, and app-control tools.
   - This closes the biggest real risk: unrestricted file reads/writes (`backend/tools/files.py:4`) and inconsistent confirmation semantics (`backend/sandbox/executor.py:294`).

2. Add prompt-injection containment for untrusted tool results.
   - Web/page/email/file content currently re-enters a tool-capable loop (`backend/brain/agent.py:571`). Tainting and gating consequential tools would reduce the blast radius of adversarial pages or emails.

3. Redesign barge-in around a single audio-device owner.
   - The current second `InputStream` plus `sd.stop()` pattern (`backend/main.py:290`, `backend/main.py:322`) is the most plausible explanation for the bus error and is a stability blocker.

4. Finish streaming for the agent path.
   - The callback exists (`backend/brain/agent.py:277`) but is not passed from `main.py` (`backend/main.py:725`). Wiring it would make the coding window feel responsive during long multi-step/code tasks.

5. Collapse local-code handling into one deterministic path and test that production path.
   - `local_code.py` is tested (`backend/test_regression.py:295`) but disabled by default (`backend/main.py:53`). The active behavior depends on model tool selection plus `find_project`/`read_project_file` (`backend/tools/projects.py:97`). One path will be easier to harden and reason about.

## Test Coverage Gaps

- No test asserts that `read_file`/`write_file` reject `.env`, `.ssh`, or paths outside approved roots.
- No test asserts that `git add`/`git commit` require explicit user intent or approval.
- No hostile web/email/file prompt-injection fixture verifies that untrusted content cannot trigger `run_shell`, `write_file`, or `navigate_browser`.
- No test simulates bridge `/api/approval` races or unauthorized local requests.
- No test covers the barge-in audio path; this likely needs a fake audio device abstraction rather than real `sounddevice`.
- No Swift unit/UI test decodes unknown activity kinds, tests reconnect after WS drop, or checks the streaming bubble -> final bubble transition.
- No integration test covers real IMAP/EventKit/Ollama failure modes; current tests intentionally stub or parse deterministic pieces (`backend/test_proactive.py:118`, `backend/test_regression.py:241`).

