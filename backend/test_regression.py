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
from datetime import datetime
from brain.agent import _tool_failed, _announces_next_action, _parse_verdict
from tools.web import _strip_filler, _is_newsy
from tools.calendar_tool import _parse_range
from tools.gmail_tool import _to_gmail_query
from tools.clipboard_tool import _looks_like_secret, _classify
from tools.notifications_tool import _extract, matches as notif_matches
from local_code import prepare_code_review

# Notification parsing/matching, pinned against the REAL macOS 15 plist shape
# observed on this Mac: {app, req:{titl,subt,body,iden}}. No DB/FDA needed.
_NOTIF_IG = _extract(
    {"app": "com.google.Chrome.framework",
     "req": {"titl": "priya._", "subt": "[www.instagram.com](https://www.instagram.com)",
             "body": "sent you a message", "iden": "p#https://www.instagram.com/"}},
    "com.google.Chrome",
)
_NOTIF_WA = _extract(
    {"app": "net.whatsapp.WhatsApp",
     "req": {"titl": "Mom", "body": "call me", "subt": "", "iden": ""}},
    "net.whatsapp.WhatsApp",
)
_NOTIF_NOISE = _extract(
    {"app": "com.google.Chrome.framework",
     "req": {"titl": "Evening plans? Shop deals", "subt": "[www.myntra.com](https://www.myntra.com)",
             "body": "Up To 50% Off", "iden": "p#https://www.myntra.com/"}},
    "com.google.Chrome",
)
# (notification, sources, expected match)
NOTIF_MATCH_CASES = [
    (_NOTIF_IG, ["instagram"], True),               # web push → matched via subt/iden
    (_NOTIF_WA, ["whatsapp"], True),                # native app → matched via bundle
    (_NOTIF_NOISE, ["whatsapp", "instagram"], False),  # Myntra deal → ignored
    (_NOTIF_IG, ["whatsapp"], False),               # wrong source → no match
]
# the extractor pulls the right fields
NOTIF_EXTRACT_OK = (_NOTIF_WA["title"] == "Mom" and _NOTIF_WA["body"] == "call me"
                    and "instagram.com" in _NOTIF_IG["subtitle"])

# (clipboard text, expected _looks_like_secret) — the reactive read and the
# proactive watcher must both refuse credentials. Passwords/keys never leave.
CLIPBOARD_SECRET_CASES = [
    ("hello world, this is normal text", False),
    ("def add(a, b):\n    return a + b", False),
    ("my password is hunter2", True),            # secret hint word
    ("nvapi-abc123def456ghi789", True),          # key prefix
    ("aB3xY9zKmN2pQr7sT", True),                 # long single-line mixed token
    ("https://example.com/some/page", False),
]

# (clipboard text, expected proactive category) — only positively-useful content
# nudges; secrets/trivia stay silent (None).
CLIPBOARD_CLASSIFY_CASES = [
    ("Traceback (most recent call last):\n  File x\nValueError: bad", "error"),
    ("How do I reverse a list in Python?", "question"),
    ("for i in range(10):\n    print(i)\n", "code"),
    ("hi", None),                                 # too trivial
    ("nvapi-secrettokenvalue1234", None),         # secret → never
]

# (spoken request, substrings that MUST appear in the Gmail search) — the
# natural-language → Gmail-search translation is pure, so we pin it without an
# account. Gmail's X-GM-RAW syntax is what makes "important/starred/from" work.
GMAIL_QUERY_CASES = [
    ("", ["is:unread"]),
    ("any unread mail", ["is:unread"]),
    ("starred emails", ["is:starred"]),
    ("important emails today", ["is:important", "newer_than:1d"]),
    ("emails from priya", ["from:priya"]),
    ("starred mail from boss this week", ["is:starred", "from:boss", "newer_than:7d"]),
]

# (timeframe phrase, expected label) — the calendar range parser is pure, so we
# can pin its boundaries without needing Calendar access.
_CAL_NOW = datetime(2026, 6, 30, 9, 0)  # a Tuesday
CAL_RANGE_CASES = [
    ("", "today"),
    ("today", "today"),
    ("what's on tomorrow", "tomorrow"),
    ("this week", "this week"),
    ("next 7 days", "this week"),
    ("this month", "this month"),
]

# (verifier reply, expected achieved) — the success verifier must fail OPEN: only
# an explicit NOT_ACHIEVED blocks completion; anything ambiguous or malformed is
# treated as achieved so it can never strand the user on its own confusion.
VERDICT_CASES = [
    ("ACHIEVED", True),
    ("NOT_ACHIEVED: nothing was staged, so the commit is empty", False),
    ("NOT ACHIEVED: the push did not run", False),
    ("The goal looks done to me.", True),         # no marker -> achieved
    ("", True),                                    # empty -> fail open
    ("ACHIEVED — file written with the requested content", True),
]

# (query, expected substrings present / absent after filler-strip) — the
# deterministic reformulation fallback keeps content words, drops scaffolding.
FILLER_CASES = [
    ("can you tell me what the weather is", ["weather"]),
    ("hey friday find out about the barcelona transfer news", ["barcelona", "transfer", "news"]),
]

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
    # File LISTING is single-shot (one ls); only batch MUTATIONS are agent work.
    ("Can you list out whatever is in my download folder?", False),
    ("sort my downloads folder by type", True),
    ("organize the files on my desktop", True),
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
    # Calendar reads are single get_calendar calls — single-shot, not the agent.
    ("what's on my calendar today", False),
    ("do i have any meetings tomorrow", False),
    ("what's my schedule this week", False),
    # News/info lookups MUST stay single-shot (one search → concise summary).
    # Regression: routed to the agent, which dumped a raw scrape as a markdown
    # doc and spoke "It seems you have provided a mix of content from Reuters".
    ("can you get me the news from around the world", False),
    ("what's the latest news", False),
    # Gmail reads (single read_email) and watchers (single watch_email) are
    # single-shot, never the agent loop.
    ("check my email", False),
    ("any new mail from priya", False),
    ("tell me when i get an important email", False),
    ("watch my inbox for starred mail", False),
    # Clipboard: read (single-shot) and watch (single-shot), never the agent.
    ("what's on my clipboard", False),
    ("summarize what i just copied", False),
    ("keep an eye on my clipboard", False),
    # Messages/notifications: read (single-shot) and watch (single-shot).
    ("any new messages", False),
    ("any whatsapp messages", False),
    ("tell me when someone messages me", False),
    ("watch for instagram dms", False),
    # Daily briefing: brief-now (single daily_briefing) and scheduled briefing
    # (single daily_briefing with a time) both stay single-shot, never the agent.
    ("brief me", False),
    ("what does my day look like", False),
    ("give me the rundown", False),
    ("brief me every morning at 8", False),
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
    ("what's on my calendar today", "get_calendar"),
    ("do i have any meetings tomorrow", "get_calendar"),
    ("check my email", "read_email"),
    ("any new mail from priya", "read_email"),
    ("tell me when i get an important email", "watch_email"),
    ("what did i just copy", "read_clipboard"),
    ("keep an eye on my clipboard", "watch_clipboard"),
    ("any new whatsapp messages", "check_messages"),
    ("tell me when i get a whatsapp message", "watch_notifications"),
    ("brief me on my day", "daily_briefing"),
    ("what does my day look like", "daily_briefing"),
    ("brief me every morning at 8", "daily_briefing"),
    # Filesystem inspection must hit run_shell (ls), NOT look_at_screen. The model
    # used to grab look_at_screen or refuse ("can't access files") because the tool
    # descriptions didn't claim folder-listing; this is the fix's regression guard.
    ("what's in my downloads folder", "run_shell"),
    ("list the files in my downloads", "run_shell"),
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

# (utterance, expected_is_complex) — NO keyword signal, so these actually hit the
# qwen2.5:3b router. With the few-shot prompt + temperature 0 they should be
# stable run-to-run; a consistent failure here is a real router regression.
ROUTER_MODEL_CASES = [
    ("compress my screenshots folder", True),
    ("what's the tallest mountain in the world", False),
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

    print("\nSUCCESS-VERIFIER VERDICT PARSING (agent):")
    for raw, exp in VERDICT_CASES:
        got, _reason = _parse_verdict(raw)
        ok = got == exp
        if not ok:
            fails.append(f"_parse_verdict({raw!r:.40})")
        print(f"  {'PASS' if ok else 'FAIL'}  achieved={got!s:5} (want {exp!s:5})  {raw[:46]!r}")

    print("\nQUERY REFORMULATION FALLBACK (web):")
    for query, must_have in FILLER_CASES:
        stripped = _strip_filler(query).lower()
        ok = all(w in stripped for w in must_have)
        if not ok:
            fails.append(f"_strip_filler({query!r:.40})")
        print(f"  {'PASS' if ok else 'FAIL'}  {stripped!r:48}  {query}")

    print("\nCALENDAR RANGE PARSING (tools):")
    for phrase, exp in CAL_RANGE_CASES:
        label, _start, _end = _parse_range(phrase, now=_CAL_NOW)
        ok = label == exp
        if not ok:
            fails.append(f"_parse_range({phrase!r:.30})")
        print(f"  {'PASS' if ok else 'FAIL'}  {label:11} (want {exp:11})  {phrase!r}")

    print("\nGMAIL QUERY TRANSLATION (tools):")
    for phrase, must_have in GMAIL_QUERY_CASES:
        query, _label = _to_gmail_query(phrase)
        ok = all(s in query for s in must_have)
        if not ok:
            fails.append(f"_to_gmail_query({phrase!r:.30})")
        print(f"  {'PASS' if ok else 'FAIL'}  {query:34} {phrase!r}")

    print("\nCLIPBOARD SECRET DETECTION (tools):")
    for text, exp in CLIPBOARD_SECRET_CASES:
        got = _looks_like_secret(text)
        ok = got == exp
        if not ok:
            fails.append(f"_looks_like_secret({text!r:.30})")
        print(f"  {'PASS' if ok else 'FAIL'}  secret={got!s:5} (want {exp!s:5})  {text[:40]!r}")

    print("\nCLIPBOARD CLASSIFICATION (tools):")
    for text, exp in CLIPBOARD_CLASSIFY_CASES:
        got, _offer = _classify(text)
        ok = got == exp
        if not ok:
            fails.append(f"_classify({text!r:.30})")
        print(f"  {'PASS' if ok else 'FAIL'}  {got!s:8} (want {exp!s:8})  {text[:36]!r}")

    print("\nNOTIFICATION PARSE + MATCH (tools):")
    if not NOTIF_EXTRACT_OK:
        fails.append("notifications _extract pulled wrong fields")
    print(f"  {'PASS' if NOTIF_EXTRACT_OK else 'FAIL'}  _extract fields (title/body/subtitle)")
    for n, src, exp in NOTIF_MATCH_CASES:
        got = notif_matches(n, src)
        ok = got == exp
        if not ok:
            fails.append(f"notif matches({n.get('title')!r}, {src})")
        print(f"  {'PASS' if ok else 'FAIL'}  match={got!s:5} (want {exp!s:5})  {n.get('title','')[:24]!r} vs {src}")

    print("\nROUTING (is_complex):")
    for utt, exp in ROUTING_CASES:
        got = is_complex(utt)
        ok = got == exp
        if not ok:
            fails.append(utt)
        print(f"  {'PASS' if ok else 'FAIL'}  complex={got!s:5} (want {exp!s:5})  {utt}")

    print("\nROUTER MODEL (no-keyword utterances hit qwen2.5:3b):")
    for utt, exp in ROUTER_MODEL_CASES:
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

    total = (len(TOOL_FAILURE_CASES) + len(NEXT_ACTION_CASES) + len(VERDICT_CASES)
             + len(FILLER_CASES) + len(CAL_RANGE_CASES) + len(GMAIL_QUERY_CASES)
             + len(CLIPBOARD_SECRET_CASES) + len(CLIPBOARD_CLASSIFY_CASES)
             + len(NOTIF_MATCH_CASES) + 1  # +1 for the _extract field check
             + len(ROUTING_CASES) + len(ROUTER_MODEL_CASES) + len(TOOL_CASES)
             + len(CONTINUITY_CASES) + len(LOCAL_CODE_CASES)
             + len(LOCAL_CODE_NEGATIVE_CASES))
    print(f"\n{total - len(fails)}/{total} passed")
    if fails:
        print("FAILED:", *[f'\n  - {u}' for u in fails])
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    run()
