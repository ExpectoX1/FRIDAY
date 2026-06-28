"""FRIDAY behavior regression suite.

One command, ~30s: checks routing + single-shot tool selection against expected
behavior, including the bugs that surfaced in real testing. Run after any change
to the brain/routing/tools so regressions show up as red lines instead of during
a hectic voice session.

    python test_regression.py

Exits non-zero if anything fails. Note: the brain is an LLM, so a rare flake is
possible; a case that fails consistently is a real regression.
"""
import sys
from brain.llm import is_complex, chat
import brain.llm as llm
from brain.agent import _tool_failed

# (tool result, expected _tool_failed) — the agent must only treat a result as a
# failure when it ANNOUNCES one, never on error-like words inside real content.
# Regression: reading code that imports HTTPException was misread as a read_file
# failure, which sent the agent flailing into committing an unrelated git repo.
TOOL_FAILURE_CASES = [
    ("from fastapi import FastAPI, HTTPException, Request, status\napp = FastAPI()", False),
    ("Liverpool error of judgement; no errors in the report", False),
    ("Successfully wrote to /tmp/x.py", False),
    ({"status": "success", "message": "Opening now."}, False),
    ("File not found: /nope.py", True),
    ("Error reading file: permission denied", True),
    ("BLOCKED: Command contains restricted shell metacharacters", True),
    ("fatal: not a git repository", True),
    ({"status": "error", "message": "bad args"}, True),
]

# (utterance, expected_is_complex) — does it route to the multi-step agent?
ROUTING_CASES = [
    ("how are you", False),
    ("who are you", False),
    ("thanks friday", False),
    ("what other functionality do you need", False),  # reflective -> chat, not agent
    ("open spotify", False),
    ("play blinding lights on spotify", False),
    ("ok babe play arz kiya hai", False),
    ("what time is it", False),
    ("where does priya live", False),  # "live" must NOT match "is live"
    ("i want to watch the good doctor on netflix", False),
    ("open twitter on chrome", False),  # single navigate, not multi-step
    ("commit my friday project", True),
    ("find and play the latest yjr video", True),
    ("markaroni is live, can you open the stream", True),
    ("play the latest yjr video", True),
    # Reminders/timers are single tool calls, not agent jobs — even when the
    # reminder body itself contains agent-y words ("remind me to commit ...").
    ("remind me to call mom in 10 minutes", False),
    ("set a timer for 5 minutes", False),
    ("remind me to commit my project at 6pm", False),
    ("what reminders do i have", False),
    # Web monitors are a single set_monitor call, even though the body sounds
    # research-y ("monitor ... and tell me ... news").
    ("monitor fabrizio for barcelona news", False),
    ("keep an eye on bitcoin price and let me know", False),
    ("monitor fabrizio romano's tweets", False),
    ("tell me when elon musk tweets", False),
]

# (utterance, expected tool name, or "reply")
TOOL_CASES = [
    ("open spotify", "open_app"),
    ("play blinding lights on spotify", "play_media"),
    ("what time is it", "get_date_time"),
    ("how are you today", "reply"),
    ("what's on my screen", "look_at_screen"),
    ("open twitter on chrome", "navigate_browser"),  # not open_app
    ("who is priya", "search_memory"),
    ("what's the latest news on football", "search_web"),
    ("read this article for me https://www.bbc.com/sport/football/12345", "read_page"),
    ("remind me to call mom in 10 minutes", "set_reminder"),
    ("set a timer for 5 minutes", "set_timer"),
    ("what reminders do i have", "list_reminders"),
    ("monitor fabrizio for barcelona transfer news", "set_monitor"),
    ("monitor fabrizio romano's tweets", "set_monitor"),  # X scraping dropped -> web monitor
]


# (last-result content, follow-up utterance, expected tool) — reference resolution
CONTINUITY_CASES = [
    ("STAY chords (URL: https://tabs.ultimate-guitar.com/tab/the-kid-laroi/stay-3421793)",
     "open the chords for me", "navigate_browser"),
    ("BBC Sport (URL: https://www.bbc.com/sport/football)", "open that page", "navigate_browser"),
    ("Markaroni video (URL: https://www.youtube.com/watch?v=abc123)", "play it", "navigate_browser"),
]


def run():
    fails = []

    print("TOOL FAILURE DETECTION (agent):")
    for result, exp in TOOL_FAILURE_CASES:
        got = _tool_failed(result)
        ok = got == exp
        if not ok:
            fails.append(f"_tool_failed({result!r:.40})")
        label = (result if isinstance(result, str) else str(result))[:48]
        print(f"  {'PASS' if ok else 'FAIL'}  failed={got!s:5} (want {exp!s:5})  {label}")

    print("\nROUTING (is_complex):")
    for utt, exp in ROUTING_CASES:
        got = is_complex(utt)
        ok = got == exp
        if not ok:
            fails.append(utt)
        print(f"  {'PASS' if ok else 'FAIL'}  complex={got!s:5} (want {exp!s:5})  {utt}")

    print("\nTOOL SELECTION (single-shot):")
    for utt, exp in TOOL_CASES:
        llm.history = []
        r = chat(utt)
        got = r.get("name") if r.get("type") == "tool" else "reply"
        ok = got == exp
        if not ok:
            fails.append(utt)
        print(f"  {'PASS' if ok else 'FAIL'}  {got:16} (want {exp:16})  {utt}")

    print("\nCONTINUITY (refer back to last result):")
    for ctx, utt, exp in CONTINUITY_CASES:
        llm.set_last_result("search_web", ctx)
        llm.history = []
        r = chat(utt)
        got = r.get("name") if r.get("type") == "tool" else "reply"
        ok = got == exp
        if not ok:
            fails.append(utt)
        print(f"  {'PASS' if ok else 'FAIL'}  {got:16} (want {exp:16})  {utt}")
    llm.set_last_result("", "")  # reset

    total = (len(TOOL_FAILURE_CASES) + len(ROUTING_CASES)
             + len(TOOL_CASES) + len(CONTINUITY_CASES))
    print(f"\n{total - len(fails)}/{total} passed")
    if fails:
        print("FAILED:", *[f'\n  - {u}' for u in fails])
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    run()
