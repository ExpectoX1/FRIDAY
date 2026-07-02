import os
import re
import time
import ollama
import json
from pathlib import Path
from brain.personality import get_personality
from tools.registry import get_tools_spec

history = []
MAX_HISTORY = 4

# qwen3:14b: 8/8 tool-selection accuracy (vs qwen2.5:7b's flaky 6/8) at the same
# ~1.2s warm latency, with stronger agentic tool discipline. MUST run with
# thinking disabled (see think=False below) or it spends seconds reasoning
# before every call. Benchmarked in bench_brain.py on a 24GB M4 Pro.
# Override e.g. FRIDAY_LOCAL_MODEL=gemma4:latest (gemma3 has no native tools).
MODEL = os.getenv("FRIDAY_LOCAL_MODEL", "qwen3:14b")
ROUTER_MODEL = "qwen2.5:3b"  # small/fast model for SIMPLE/COMPLEX routing

# Keep models resident between calls. We alternate brain (gemma4) and router
# (qwen3b) every turn; without this, Ollama can evict one to load the other,
# paying a multi-second reload each time. A long TTL pins both warm.
KEEP_ALIVE = "30m"

# ── Brain backend (experiment) ───────────────────────────────────────────────
# FRIDAY_BRAIN=cloud routes chat()/agent_chat() to Groq (free, very fast) for
# A/B testing against local gemma4. Everything else (router, memory) stays
# local. Default is "ollama" so nothing changes unless the flag is set.
BACKEND = os.getenv("FRIDAY_BRAIN", "ollama").lower()
# gpt-oss-20b and llama-3.1-8b-instant emit reliable native tool_calls on Groq;
# llama-3.3-70b intermittently returns malformed calls (tool_use_failed).
CLOUD_MODEL = os.getenv("FRIDAY_CLOUD_MODEL", "openai/gpt-oss-20b")
_groq_client = None


def _groq():
    global _groq_client
    if _groq_client is None:
        from openai import OpenAI
        from dotenv import load_dotenv

        load_dotenv()
        key = os.getenv("GROQ_API") or os.getenv("GROQ_API_KEY")
        _groq_client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
    return _groq_client


def _to_openai_messages(messages: list) -> list:
    """Translate our Ollama-style message list to OpenAI/Groq format: tool-call
    arguments become JSON strings and tool results get a tool_call_id linking
    them to the preceding assistant call."""
    out, last_id, n = [], None, 0
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            n += 1
            last_id = f"call_{n}"
            fn = m["tool_calls"][0]["function"]
            out.append(
                {
                    "role": "assistant",
                    "content": m.get("content") or "",
                    "tool_calls": [
                        {
                            "id": last_id,
                            "type": "function",
                            "function": {
                                "name": fn["name"],
                                "arguments": json.dumps(fn.get("arguments", {})),
                            },
                        }
                    ],
                }
            )
        elif role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": last_id or "call_1",
                    "content": str(m.get("content", "")),
                }
            )
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return out


def _call_brain(messages: list) -> dict:
    """Run one brain turn on the active backend. Returns a normalized dict:
    {"content": str, "tool": (name, args_dict) | None}."""
    if BACKEND == "cloud":
        # Groq's free models intermittently return unparseable output
        # (output_parse_failed / tool_use_failed); a retry usually recovers.
        last_err = None
        for attempt in range(3):
            try:
                r = _groq().chat.completions.create(
                    model=CLOUD_MODEL,
                    messages=_to_openai_messages(messages),
                    tools=get_tools_spec(),
                )
                m = r.choices[0].message
                content = (m.content or "").strip()
                if m.tool_calls:
                    fn = m.tool_calls[0].function
                    args = (
                        json.loads(fn.arguments)
                        if isinstance(fn.arguments, str)
                        else (fn.arguments or {})
                    )
                    return {"content": content, "tool": (fn.name, args)}
                return {"content": content, "tool": None}
            except Exception as e:
                last_err = e
                continue
        return {"content": f"Sorry Sir, the cloud brain hit an error: {last_err}", "tool": None}

    # think=False keeps Qwen3 from running chain-of-thought before each tool
    # call (which adds ~5-8s). Ignored by non-thinking models.
    response = ollama.chat(
        model=MODEL, messages=messages, tools=get_tools_spec(),
        keep_alive=KEEP_ALIVE, think=False,
    )
    m = response.message
    content = (m.content or "").strip()
    if m.tool_calls:
        c = m.tool_calls[0].function
        return {"content": content, "tool": (c.name, dict(c.arguments))}
    return {"content": content, "tool": None}


def call_brain_stream(messages: list):
    """Yields either ("token", text_chunk) or ("tool", (name, args)) or ("reply", full_content)"""
    if BACKEND == "cloud":
        res = _call_brain(messages)
        if res.get("tool"):
            yield "tool", res["tool"]
        else:
            yield "reply", res["content"]
        return

    response_stream = ollama.chat(
        model=MODEL, messages=messages, tools=get_tools_spec(),
        keep_alive=KEEP_ALIVE, think=False, stream=True
    )

    full_content = ""
    tool_calls = []

    for chunk in response_stream:
        m = chunk.message
        if m.tool_calls:
            for tc in m.tool_calls:
                tool_calls.append(tc)
        
        if m.content:
            full_content += m.content
            if not tool_calls:
                yield "token", m.content

    if tool_calls:
        # First call wins — same convention as the non-streaming _call_brain
        # (tool_calls[0]), so a request behaves identically on either path.
        tc = tool_calls[0].function
        yield "tool", (tc.name, dict(tc.arguments))
    else:
        yield "reply", full_content.strip()


# Most recent tool result, injected into the next single-shot turn so the user
# can refer back to it ("open it", "open the chords", "the second one"). Single-
# shot otherwise forgets tool output between turns, which made follow-ups fail.
_last_result: tuple | None = None


def set_last_result(label: str, content) -> None:
    global _last_result
    text = str(content).strip()
    _last_result = (label, text[:1500]) if text else None


# Does the utterance refer back to a previous result ("open it", "which of
# those are folders", "read the article")? Only then is the last-result block
# injected below. Injecting it on EVERY turn distorted tool selection on
# unrelated questions: with an `ls` listing + the navigate_browser imperative
# in the system prompt, "what's the latest news on X" picked set_monitor 5/5
# instead of search_web 5/5 (live misroute, 2026-07-02).
_REFERS_TO_PRIOR = re.compile(
    r"\b(it|that|this|those|these|them|the (page|link|site|chords|tab|video|"
    r"result|results|article|file|files|folder|list|one|first one|second one))\b",
    re.IGNORECASE,
)


def _system_context(message: str = "") -> str:
    base = get_personality(native_tools=True)
    if _last_result and (not message or _REFERS_TO_PRIOR.search(message)):
        label, content = _last_result
        base += (
            f"\n\n[Most recent result — from {label}]:\n{content}\n"
            "IMPORTANT: If the user now says to open / show / go to / pull up "
            "'it', 'that', 'the page', 'the link', 'the chords', 'the site', "
            "etc., they mean a URL in the result above. You MUST immediately call "
            "navigate_browser with that exact URL. Never ask which page, never "
            "paste the content as text, never describe what you'll do — just call "
            "navigate_browser with the URL."
        )
    return base


_REFERENTIAL_OPEN = re.compile(
    r"\b(open|show|pull up|go to|take me to|play|launch)\b.*"
    r"\b(it|that|this|the (page|link|site|chords|tab|video|result|article|one))\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s)\"']+")


def _referential_open(message: str):
    """Deterministically resolve "open it / that page / the chords" to the URL
    in the most recent result, instead of relying on the model to make the leap
    (which it does unreliably). Returns a navigate_browser tool dict or None."""
    if not _last_result or not _REFERENTIAL_OPEN.search(message):
        return None
    urls = _URL_RE.findall(_last_result[1])
    return {"type": "tool", "name": "navigate_browser", "args": {"url": urls[0]}} if urls else None


def cloud_available() -> bool:
    """A Groq key is configured, so cloud routing is possible."""
    return bool(os.getenv("GROQ_API") or os.getenv("GROQ_API_KEY"))


# System prompt for interpreting a tool result into a SPOKEN answer (used with
# the stateless ask() by main.py's LLM_INTERPRET path). Live regression
# (2026-07-02): interpretation used to run through chat(), which stored the raw
# search dump in history as a fake USER turn — the model answered "it seems
# you're sharing a detailed report..." and produced a 700-token markdown
# document with tables and emojis straight into the TTS pipe.
INTERPRET_SYSTEM = (
    "You are FRIDAY, a voice assistant. You are given the user's request and "
    "raw content fetched by YOUR OWN tools (web search results, a page, a "
    "file, or clipboard text). The content is tool output you retrieved — the "
    "user has NOT seen it and did not write it; never say they shared or "
    "provided it. Answer the user's request from that content in 2-4 short "
    "sentences that sound natural read aloud. Plain sentences only: no "
    "markdown, no headers, no tables, no bullet lists, no emojis. Lead with "
    "the key facts. Do not ask what they want — just answer."
)


def ask(prompt: str, system: str | None = None, use_cloud: bool = False) -> str:
    """Stateless single-turn brain call — no tools, no history. Routes to the
    cloud brain (Groq) when use_cloud and a key is present, else local qwen3.
    Used for follow-up code Q&A where we want a focused answer, optionally from
    the more capable cloud model for deep questions."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    if use_cloud and cloud_available():
        try:
            r = _groq().chat.completions.create(model=CLOUD_MODEL, messages=messages)
            return (r.choices[0].message.content or "").strip()
        except Exception:
            pass  # cloud hiccup — fall through to local

    resp = ollama.chat(model=MODEL, messages=messages, keep_alive=KEEP_ALIVE, think=False)
    return (resp.message.content or "").strip()


def chat(message: str) -> dict:
    """Single-shot chat — used for simple queries and tool result interpretation.

    Uses native Ollama tool calling: the model either emits a structured
    tool_call or returns plain text. No more JSON-in-text parsing.
    """
    global history

    # Deterministic "open it / that page / the chords" -> last result's URL,
    # before involving the model (which resolves these unreliably).
    ref = _referential_open(message)
    if ref:
        return ref

    history.append({"role": "user", "content": message})
    trimmed = history[-MAX_HISTORY:]

    messages = [{"role": "system", "content": _system_context(message)}] + trimmed
    res = _call_brain(messages)

    if res["tool"]:
        name, args = res["tool"]
        # Don't write a synthetic "[called X]" turn into history — the model
        # echoes it back as a reply on the next turn. Drop the triggering user
        # message too so history stays clean conversational text only.
        history.pop()
        return {"type": "tool", "name": name, "args": args}

    history.append({"role": "assistant", "content": res["content"]})
    return {"type": "reply", "content": res["content"]}


def chat_stream(message: str):
    """Single-shot chat with token streaming. Yields either:
    - ("token", text_chunk)
    - ("tool", (name, args))
    - ("reply", full_content)
    """
    global history

    ref = _referential_open(message)
    if ref:
        yield "tool", (ref["name"], ref["args"])
        return

    history.append({"role": "user", "content": message})
    trimmed = history[-MAX_HISTORY:]

    messages = [{"role": "system", "content": _system_context(message)}] + trimmed

    has_tool = False
    full_content = ""

    for event_type, data in call_brain_stream(messages):
        if event_type == "token":
            full_content += data
            yield "token", data
        elif event_type == "tool":
            has_tool = True
            name, args = data
            history.pop()
            yield "tool", (name, args)
        elif event_type == "reply":
            full_content = data

    if not has_tool:
        history.append({"role": "assistant", "content": full_content})
        yield "reply", full_content


def agent_chat(messages: list) -> dict:
    """
    Agent loop chat — native tool calling over a real message list.

    The caller owns the conversation (system, user, assistant tool_calls, and
    tool-result turns). We return a uniform dict the loop can act on:
      tool  -> {"type":"tool","name","args","thought","raw_message"}
      reply -> {"type":"reply","content","thought"}
    `raw_message` is the assistant turn to append back into `messages` so the
    model sees its own prior tool call on the next iteration.
    """
    res = _call_brain(messages)
    thought = res["content"]

    if res["tool"]:
        name, args = res["tool"]
        # Plain-dict form of the assistant turn so `messages` stays fully
        # JSON-serializable (it gets stored in pending_state and logged).
        raw_message = {
            "role": "assistant",
            "content": thought,
            "tool_calls": [{"function": {"name": name, "arguments": args}}],
        }
        return {
            "type": "tool",
            "name": name,
            "args": args,
            "thought": thought,
            "raw_message": raw_message,
        }

    return {"type": "reply", "content": thought, "thought": thought}


def agent_chat_stream(messages: list):
    """Agent loop chat with token streaming. Yields either:
    - ("token", text_chunk)
    - ("tool", tool_dict)
    - ("reply", reply_dict)
    """
    if BACKEND == "cloud":
        res = agent_chat(messages)
        if res["type"] == "tool":
            yield "tool", res
        else:
            yield "reply", res
        return

    response_stream = ollama.chat(
        model=MODEL, messages=messages, tools=get_tools_spec(),
        keep_alive=KEEP_ALIVE, think=False, stream=True
    )

    full_content = ""
    tool_calls = []

    for chunk in response_stream:
        m = chunk.message
        if m.tool_calls:
            for tc in m.tool_calls:
                tool_calls.append(tc)
        
        if m.content:
            full_content += m.content
            if not tool_calls:
                yield "token", m.content

    if tool_calls:
        # First call wins — matches _call_brain's tool_calls[0].
        tc = tool_calls[0].function
        name = tc.name
        args = dict(tc.arguments)
        raw_message = {
            "role": "assistant",
            "content": full_content,
            "tool_calls": [{"function": {"name": name, "arguments": args}}],
        }
        yield "tool", {
            "type": "tool",
            "name": name,
            "args": args,
            "thought": full_content,
            "raw_message": raw_message,
        }
    else:
        yield "reply", {
            "type": "reply",
            "content": full_content.strip(),
            "thought": full_content.strip(),
        }


COMPLEX_SIGNALS = [
    "and then", "after that", "first ", "step by step", "push", "commit", "deploy",
    "research", "find and", "open and", "search and", "write and", "create and",
    "write a test", "write tests", "create a test", "create tests", "add tests",
    "test file", "testing of",
    "help me", "figure out", "work out", "go to", "navigate to",
    "open chrome and",
    # Batch file MUTATIONS stay on the agent (multi-step, write a script). Read-only
    # LISTING ("what's in my downloads", "list the files") does NOT — it's a single
    # run_shell(ls) and the agent actually picks the WRONG tool for it (look_at_screen
    # / refuse), while single-shot nails run_shell. So listing is pinned SIMPLE below.
    "sort", "organize", "clean", "tidy", "rename",
    # Discovery intents — need a web search before acting, so they must run in
    # the agent loop (search_web -> navigate_browser), never single-shot.
    # Checked before SIMPLE_SIGNALS so "open the stream" beats the "open " pin.
    "stream", "livestream", "is live", "video",
]

# Obvious single-step intents — force single-shot so casual phrasing like
# "ok babe play arz kiya hai" never gets mis-escalated to the agent loop.
# Checked AFTER COMPLEX_SIGNALS so "find and play ..." still routes to the agent.
SIMPLE_SIGNALS = [
    "play ", "pause", "resume", "stop", "skip", "next song", "previous song",
    "volume", "open ", "close ", "launch ", "quit ", "what time", "what's the time",
    # Chit-chat / greetings — pure conversation, must stay single-shot and never
    # hit the heavy agent loop (the qwen router tends to over-classify these).
    "how are you", "how are things", "how's it going", "how is it going",
    "what's up", "thank you", "thanks", "good morning", "good afternoon",
    "good evening", "good night", "tell me a joke", "who are you",
    "what other functionality",
    # Calendar reads are a single get_calendar call — keep them single-shot.
    "my calendar", "my schedule", "my agenda", "any meetings",
    "meetings today", "meetings tomorrow", "on my calendar",
    "what's on today", "what's on tomorrow", "whats on my",
    # News / info lookups are a single search → summarize. They MUST stay
    # single-shot so the dedicated, concise spoken-answer summarizer handles
    # them; the agent loop free-forms and dumps the raw scrape as a markdown
    # document (it narrated a Reuters homepage instead of reading the news).
    "the news", "world news", "latest news", "news from", "news around",
    "news today", "the headlines", "headlines", "what's happening in the world",
    "whats happening in the world", "what's going on in the world",
    # Gmail reads are a single read_email call — keep them single-shot.
    "my email", "my emails", "my inbox", "my mail", "check my email",
    "check my mail", "read my email", "read my mail", "any new mail",
    "any unread", "emails from", "new mail", "any important email",
    # Clipboard companion — a single read_clipboard call, single-shot.
    "clipboard", "what did i copy", "what i copied", "i just copied",
    "what i just copied",
    # Messages/notifications read — a single check_messages call, single-shot.
    "any messages", "any new messages", "any dms", "new messages",
    "check my messages", "any whatsapp", "any instagram",
    # File LISTING is one run_shell(ls) — single-shot picks run_shell reliably,
    # the agent doesn't. (Mutations like sort/organize stay COMPLEX, checked first.)
    "in my download", "in my desktop folder", "on my desktop",
    "list the files", "list files in", "what files are", "list out whatever",
    "contents of my", "what do i have in my",
    # Daily briefing — a single daily_briefing call, single-shot.
    "brief me", "my briefing", "morning briefing", "the rundown",
    "give me the rundown", "what's my day", "whats my day", "how's my day",
    "hows my day", "my day look", "my day looking",
]

# Proactive single tool calls (reminders, timers, monitors). Checked BEFORE
# COMPLEX_SIGNALS because the request *body* often contains agent-y words
# ("remind me to commit the project at 6pm", "monitor X and tell me") that would
# otherwise mis-escalate to the multi-step agent loop.
REMINDER_SIGNALS = [
    "remind me", "set a timer", "set a reminder", "timer for", "wake me",
    "cancel my timer", "cancel the timer", "cancel my reminder",
    "list my reminders", "what reminders", "what timers",
    # Web / X monitors — "watch for X and tell me", "monitor Fabrizio's tweets"
    "monitor ", "keep an eye on", "keep me posted", "let me know when",
    "let me know if", "notify me when", "alert me when", "watch for",
    "tell me when", "stop watching", "stop monitoring",
    "tweets", "tweet", "on twitter", " on x ", "posts on x",
    # Email watchers are a single watch_email call (proactive), not the agent.
    "watch my email", "watch my inbox", "watch my mail", "alert me about",
    # Clipboard watcher — single watch_clipboard call.
    "watch my clipboard", "keep an eye on my clipboard", "stop watching my clipboard",
    # Notification/message watcher — single watch_notifications call.
    "watch my notifications", "watch for messages", "watch for whatsapp",
    "watch for instagram", "watch for dms", "tell me when someone messages",
    "stop watching my notifications",
    # Scheduled daily briefing — a single daily_briefing(when=...) call.
    "brief me every", "briefing every", "daily briefing", "brief me each",
]


# The router only runs for utterances with NO keyword signal — the genuinely
# ambiguous middle. A 3b model is reliable there only if it's shown the decision
# boundary, so we give it a terse rubric plus hard few-shot examples (the cases
# that actually flaked in testing) and decode at temperature 0. This is the
# whole router-reliability fix: better priors + determinism, not more keywords.
# NOTE (bench_router.py, 2026-07-02): do NOT enrich this rubric. Teaching it
# about proactive one-call tools (watch/remind/brief = SIMPLE) dropped raw
# accuracy 65% -> 63% and destabilized previously-passing cases ("set a timer
# for 5 minutes" flipped to COMPLEX). At 3b, more instruction text means more
# confusion — the keyword pins carry proactive intents; the router only needs
# to handle the genuinely ambiguous middle, which it does (4/4).
_ROUTER_SYSTEM = (
    "You route a voice assistant's request to one of two execution paths. "
    "Reply ONLY with the JSON classification.\n"
    "SIMPLE = can be done in ONE action or is pure conversation: open/close an "
    "app, play a named song/show, the date/time, a fact or chit-chat question "
    "(even if it needs one web lookup).\n"
    "COMPLEX = needs MULTIPLE steps or search-then-act: find-then-play a video, "
    "batch file work (sort/organize/rename/clean a folder), git (commit/push/"
    "deploy), writing/running a script, or researching and comparing.\n"
    "When the request implies discovering something first and THEN acting on it, "
    "it is COMPLEX."
)

_ROUTER_FEWSHOT = [
    {"role": "user", "content": "what's the weather like tomorrow"},
    {"role": "assistant", "content": '{"classification": "SIMPLE"}'},
    {"role": "user", "content": "put together a summary of what's in my downloads folder"},
    {"role": "assistant", "content": '{"classification": "COMPLEX"}'},
    {"role": "user", "content": "grab the newest markaroni upload and put it on"},
    {"role": "assistant", "content": '{"classification": "COMPLEX"}'},
    {"role": "user", "content": "who won the match last night"},
    {"role": "assistant", "content": '{"classification": "SIMPLE"}'},
    {"role": "user", "content": "get me the latest news from around the world"},
    {"role": "assistant", "content": '{"classification": "SIMPLE"}'},
    {"role": "user", "content": "back up my notes folder and zip it"},
    {"role": "assistant", "content": '{"classification": "COMPLEX"}'},
    {"role": "user", "content": "what's the capital of portugal"},
    {"role": "assistant", "content": '{"classification": "SIMPLE"}'},
]


# Every routing decision appends one JSONL line here: which path the utterance
# took (agent vs single-shot) and WHICH TIER decided it (a keyword pin or the
# router model). This is the dataset for making routing data-driven: misroutes
# observed in daily use can be relabeled and folded into the router's few-shot
# set / the regression suite, instead of guessing at new keywords.
ROUTING_LOG = Path.home() / "FRIDAY" / "logs" / "routing.jsonl"


def _routed(message: str, decision: bool, source: str) -> bool:
    try:
        ROUTING_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ROUTING_LOG, "a") as f:
            f.write(json.dumps(
                {"ts": time.time(), "utterance": message,
                 "complex": decision, "source": source},
                ensure_ascii=False) + "\n")
    except Exception:
        pass
    return decision


def classify_with_router(message: str) -> bool:
    """Raw qwen2.5:3b SIMPLE/COMPLEX classification — no keyword tiers in front.
    Raises on backend errors; is_complex catches and falls back. Also called
    directly by bench_router.py to measure the model's accuracy alone."""
    response = ollama.chat(
        model=ROUTER_MODEL,
        messages=[{"role": "system", "content": _ROUTER_SYSTEM}]
        + _ROUTER_FEWSHOT
        + [{"role": "user", "content": message}],
        format={
            "type": "object",
            "properties": {
                "classification": {"type": "string", "enum": ["SIMPLE", "COMPLEX"]}
            },
            "required": ["classification"],
        },
        keep_alive=KEEP_ALIVE,
        # temperature 0 makes the 3b classifier deterministic — the same
        # utterance always routes the same way, killing the run-to-run
        # flakiness where a borderline request sometimes dropped to SIMPLE.
        options={"temperature": 0},
    )
    data = json.loads(response.message.content.strip())
    return data.get("classification") == "COMPLEX"


def is_complex(message: str) -> bool:
    """Routes an utterance to the agent loop (multi-step) vs single-shot chat.

    Two-tier for speed without sacrificing recall:
      1. Keyword heuristic — if any COMPLEX_SIGNAL is present we route to the
         agent instantly, no LLM call at all.
      2. Otherwise a fast qwen2.5:3b classifier catches multi-step requests
         phrased without an obvious keyword (e.g. "grab the latest YJR video
         and put it on"). This replaces the old per-turn gemma3:12b call,
         which was ~5-10x slower for the same job.
    The heuristic is also the fallback if the router errors out.
    Every decision is logged to ROUTING_LOG with the tier that made it.
    """
    text_lower = message.lower().strip()
    if any(s in text_lower for s in REMINDER_SIGNALS):
        return _routed(message, False, "reminder_pin")

    if any(s in text_lower for s in COMPLEX_SIGNALS):
        return _routed(message, True, "complex_pin")

    if any(s in text_lower for s in SIMPLE_SIGNALS):
        return _routed(message, False, "simple_pin")

    try:
        return _routed(message, classify_with_router(message), "router")
    except Exception:
        # heuristic already said not-complex; default to single-shot
        return _routed(message, False, "router_error")
