"""FRIDAY conversation-level regression suite.

test_regression.py checks single turns in isolation; this suite drives scripted
MULTI-TURN sessions through the exact production path (main.process_turn:
confirmation flow -> routing -> brain -> tool dispatch -> interpretation ->
history), because every live bug so far lived in the seams BETWEEN turns:
context bleed, history pollution, and the approval dead end were all invisible
to single-turn tests and were found by voice — this suite finds them in CI.

    python test_conversations.py     (~30-60s with warm models)

What's real: routing, the brain (tool SELECTION), interpretation (spoken
answers), history, pending-confirmation state. What's faked: the audio layer
(whisper/kokoro load at import — stubbed before importing main), tool
EXECUTION (recorded calls, canned results — no real side effects), and the
memory store. Exits non-zero on failure; a rare LLM flake is possible, a
consistent failure is a real regression.
"""
import asyncio
import queue
import sys
import types


# ── stub the audio layer BEFORE importing main (models load at import) ───────
def _stub_module(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod


_stub_module(
    "voice.stt",
    listen=lambda *a, **k: None,
    transcribe=lambda *a, **k: "",
    rms=lambda *a, **k: 0.0,
    _input_device=lambda: None,
    SAMPLE_RATE=16000,
    BLOCK_DURATION=0.1,
)
_stub_module(
    "voice.tts",
    generate=lambda *a, **k: None,
    play=lambda *a, **k: None,
    generate_stream=lambda *a, **k: iter(()),
)

import main  # noqa: E402  — after the stubs, deliberately
import brain.llm as llm  # noqa: E402
import brain.agent as agent_mod  # noqa: E402
from brain import code_context  # noqa: E402
from tools.registry import TOOLS  # noqa: E402
from memory.retrieve import NO_MEMORY  # noqa: E402


# ── fake tool execution: record every call, return canned results ────────────
class Recorder:
    def __init__(self):
        self.calls = []              # (tool_name, kwargs) in call order
        self.results = {}            # tool_name -> canned result for this scenario
        self.executor_run_result = "Command executed successfully."
        self.executed = []           # commands run via the CONFIRMED path

    def tool(self, name):
        def fake(**kwargs):
            self.calls.append((name, kwargs))
            return self.results.get(name, {"status": "success", "message": f"{name} done."})
        return fake

    def executor_run(self, command):
        self.calls.append(("run_shell", {"command": command}))
        return self.executor_run_result

    def executor_execute(self, command):
        self.executed.append(command)
        return "Command executed successfully."

    def names(self):
        return [n for n, _ in self.calls]

    def shell_commands(self):
        return [a.get("command", "") for n, a in self.calls if n == "run_shell"]


rec = Recorder()
for _name in TOOLS:
    TOOLS[_name]["function"] = rec.tool(_name)

main.executor_run = rec.executor_run
agent_mod.executor_run = rec.executor_run
agent_mod.executor_execute = rec.executor_execute
main.THINKING_CUES = False           # no latency-filler speech in tests


async def _no_store(text):
    return None

main.store = _no_store


def drain_speech() -> str:
    """Everything FRIDAY queued for TTS since the last drain."""
    parts = []
    try:
        while True:
            parts.append(str(main.text_queue.get_nowait()))
    except queue.Empty:
        pass
    return " ".join(parts)


async def turn(text: str) -> str:
    await main.process_turn(text)
    await asyncio.sleep(0.01)        # let the fire-and-forget store task finish
    return drain_speech()


def reset():
    rec.calls.clear()
    rec.executed.clear()
    rec.results.clear()
    rec.results["search_memory"] = NO_MEMORY
    rec.executor_run_result = "Command executed successfully."
    llm.history = []
    llm.set_last_result("", "")
    code_context.clear()
    main.pending_confirmation["active"] = False
    main.pending_confirmation["state"] = None
    drain_speech()


results = []


def check(name: str, ok, detail: str = ""):
    ok = bool(ok)
    results.append((name, ok))
    line = f"  {'PASS' if ok else 'FAIL'}  {name}"
    if detail and not ok:
        line += f"  [{detail}]"
    print(line)


# ── scenarios ─────────────────────────────────────────────────────────────────

_LS_RESULT = ("Files\nArchives\nChess (mac)\nDmg Files\nDocuments\nHtml Files\n"
              "Images\nPLAN.md\nTLauncher.v17\nVideos\nXlsx Files")

_NEWS_RESULT = (
    "Julián Alvarez transfer news: Barcelona have submitted a 130 million euro "
    "offer for the Atlético Madrid forward, who wants to leave. Atlético demand "
    "150 million upfront. Alvarez, 26, has 20 goals in 49 games this season and "
    "is seen as Lewandowski's replacement. The deal is expected after the 2026 "
    "World Cup. (URL: https://www.skysports.com/football/alvarez-barca-9921)"
)


async def scenario_context_bleed():
    """The 2026-07-02 live session: a folder listing, then an unrelated news
    question. The listing's context must not flip the news turn's tool choice
    (it picked set_monitor live), and the spoken answer must be clean prose."""
    print("\nS1 CONTEXT BLEED (listing, then unrelated news question):")
    reset()
    rec.executor_run_result = _LS_RESULT
    spoken = await turn("What's in my downloads folder?")
    check("listing ran ls via run_shell", any("ls" in c for c in rec.shell_commands()),
          str(rec.names()))
    check("listing spoken from the result", "PLAN.md" in spoken, spoken[:80])

    rec.results["search_web"] = _NEWS_RESULT
    spoken = await turn("What's the latest news of Alvarez to Barcelona?")
    low = spoken.lower()
    check("news turn picked search_web", "search_web" in rec.names(), str(rec.names()))
    check("news turn did NOT register a monitor", "set_monitor" not in rec.names(),
          str(rec.names()))
    check("spoken answer is plain prose (no markdown)",
          spoken and not any(m in spoken for m in ("##", "**", "|")), spoken[:100])
    check("doesn't accuse the user of sharing the content",
          not any(m in low for m in ("you shared", "you provided", "you're sharing",
                                     "you've shared", "you have provided")), spoken[:100])
    check("actually answers the question", "alvarez" in low or "barcelona" in low,
          spoken[:100])

    # Bare "it" is grammar, not a reference — "what time is it" right after a
    # result must NOT get the prior-result block injected (it made the model
    # refuse get_date_time with "I don't have access to real-time information").
    rec.results["get_date_time"] = "It's 3:04 PM on Thursday, July 2nd."
    spoken = await turn("what time is it")
    check("bare 'it' doesn't drag in prior context",
          "get_date_time" in rec.names() and "3:04" in spoken, spoken[:80])


async def scenario_continuity():
    """Search result, then "open that page" — must navigate to the EXACT URL
    from the previous turn's result, not ask which page or re-search."""
    print("\nS2 CONTINUITY (search, then 'open that page'):")
    reset()
    rec.results["search_web"] = _NEWS_RESULT
    await turn("what's the latest news on football")
    await turn("open that page")
    nav = [a for n, a in rec.calls if n == "navigate_browser"]
    check("navigate_browser called", nav, str(rec.names()))
    check("with the exact URL from the last result",
          nav and nav[0].get("url") == "https://www.skysports.com/football/alvarez-barca-9921",
          str(nav[:1]))


async def scenario_confirmation_resume():
    """A RISKY command from the single-shot path: approval must be ARMED (the
    live dead-end bug: it asked but stored nothing), "yes" must actually run
    the command, and the resumed reply must land in history as plain text."""
    print("\nS3 CONFIRMATION (single-shot risky command, then 'yes'):")
    reset()
    rec.executor_run_result = "NEEDS_CONFIRMATION: ls ~/Downloads"
    spoken = await turn("list the files in my downloads")
    check("asked for approval", "approval" in spoken.lower(), spoken[:80])
    check("pending confirmation ARMED", main.pending_confirmation["active"])

    spoken = await turn("yes")
    check("confirmed command actually executed", rec.executed == ["ls ~/Downloads"],
          str(rec.executed))
    check("pending cleared after approval", not main.pending_confirmation["active"])
    check("history holds plain text, not JSON blobs",
          llm.history and all(not str(m.get("content", "")).lstrip().startswith("{")
                              for m in llm.history),
          str(llm.history[-1:]))


async def scenario_unrelated_clears_pending():
    """Pending approval + an unrelated request: the stale confirmation must be
    dropped and the new request must be handled normally."""
    print("\nS4 PENDING + UNRELATED INPUT (approval superseded):")
    reset()
    rec.executor_run_result = "NEEDS_CONFIRMATION: mkdir /tmp/x"
    await turn("list the files in my downloads")
    check("pending armed", main.pending_confirmation["active"])

    rec.results["get_date_time"] = "It's 3:04 PM on Thursday, July 2nd."
    spoken = await turn("what time is it")
    check("unrelated input cleared the pending approval",
          not main.pending_confirmation["active"])
    check("and was answered normally", "3:04" in spoken, spoken[:80])
    check("the risky command was NEVER executed", rec.executed == [], str(rec.executed))


def run():
    for scenario in (scenario_context_bleed, scenario_continuity,
                     scenario_confirmation_resume, scenario_unrelated_clears_pending):
        asyncio.run(scenario())

    passed = sum(1 for _, ok in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    if passed != len(results):
        print("FAILED:", *[f"\n  - {n}" for n, ok in results if not ok])
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    run()
