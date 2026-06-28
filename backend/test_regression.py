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
from brain.agent import _tool_failed, _announces_next_action
from local_code import prepare_code_review

# (reply text, expected _announces_next_action) — a reply that only ANNOUNCES an
# inspection it hasn't done ("Let me take a look at main.py") must not count as
# completion; a real answer (even one ending with "let me know" / "I'll fix X")
# must. Regression: the agent stopped after `ls`, promising to read main.py and
# never doing it.
NEXT_ACTION_CASES = [
    ("I see the files. Let me take a look at the main file, main.py, to understand what it does.", True),
    ("Let me check its contents to provide feedback.", True),
    ("I'll read the file now.", True),
    ("It's a URL shortener using FastAPI. It exposes /shorten and /stats. Let me know if you want more.", False),
    ("It does three things: shorten URLs, redirect, and track clicks. The code is solid.", False),
    ("I'll fix the rate limiting for you.", False),
    ("Done, Sir.", False),
]

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
    ("Can you write a test file which will do the testing of these functions?", True),
    ("Can you list out whatever is in my download folder?", True),
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

LOCAL_CODE_CASES = [
    ("I wanted your opinion on one of my projects. It's called teeny URL.", "teenyurl", "main.py"),
    ("Hi Friday, I want you to find out teeny URL project from my directories from my project directory", "teenyurl", "main.py"),
    ("Find the project teeny URL from my project's directory", "teenyurl", "main.py"),
    ("review the Teeny URL project", "teenyurl", "main.py"),
    ("review the Teeny URR project", "teenyurl", "main.py"),
    ("audit the teeny URL repo", "teenyurl", "main.py"),
    ("does the teeny URL app look clean", "teenyurl", "main.py"),
    ("check out the teeny oral project and in that check out main dot p y", "teenyurl", "main.py"),
    ("what is the main dot p by file do in the teeny URL folder", "teenyurl", "main.py"),
]

LOCAL_CODE_NEGATIVE_CASES = [
    "what do you think about this project idea",
    "search the web for tiny url implementations",
    "Can you write a test file which will do the testing of these functions?",
    "Can you list out whatever is in my download folder?",
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

    print("\nANNOUNCED-NEXT-ACTION DETECTION (agent):")
    for text, exp in NEXT_ACTION_CASES:
        got = _announces_next_action(text)
        ok = got == exp
        if not ok:
            fails.append(f"_announces_next_action({text!r:.40})")
        print(f"  {'PASS' if ok else 'FAIL'}  announce={got!s:5} (want {exp!s:5})  {text[:46]}")

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

    print("\nLOCAL CODE RESOLUTION:")
    for utt, exp_project, exp_file in LOCAL_CODE_CASES:
        request = prepare_code_review(utt)
        got_project = request.project.name if request else None
        got_file = request.files[0].name if request and request.files else None
        ok = got_project == exp_project and got_file == exp_file
        if not ok:
            fails.append(utt)
        print(f"  {'PASS' if ok else 'FAIL'}  {got_project}/{got_file} (want {exp_project}/{exp_file})  {utt}")

    print("\nLOCAL CODE NON-MATCHES:")
    for utt in LOCAL_CODE_NEGATIVE_CASES:
        request = prepare_code_review(utt)
        ok = request is None
        if not ok:
            fails.append(utt)
        got = f"{request.project.name}/{request.files[0].name if request.files else '-'}" if request else "None"
        print(f"  {'PASS' if ok else 'FAIL'}  {got:16} (want None)  {utt}")

    total = (len(TOOL_FAILURE_CASES) + len(NEXT_ACTION_CASES) + len(ROUTING_CASES)
             + len(TOOL_CASES) + len(CONTINUITY_CASES) + len(LOCAL_CODE_CASES)
             + len(LOCAL_CODE_NEGATIVE_CASES))
    print(f"\n{total - len(fails)}/{total} passed")
    if fails:
        print("FAILED:", *[f'\n  - {u}' for u in fails])
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    run()
