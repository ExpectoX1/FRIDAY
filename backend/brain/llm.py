import os
import re
import ollama
import json
from brain.personality import get_personality
from tools.registry import get_tools_spec

history = []
MAX_HISTORY = 4

# qwen2.5:7b: equal tool-selection accuracy to gemma4 but ~2.8x faster
# (~700ms vs 2-6s typical) and half the size — benchmarked in bench_brain.py.
# Override for A/B testing, e.g. FRIDAY_LOCAL_MODEL=gemma4:latest (gemma3 does
# NOT support native tools, so it can't be the brain).
MODEL = os.getenv("FRIDAY_LOCAL_MODEL", "qwen2.5:7b")
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
            # Don't crash the conversation on a transient cloud error.
            return {"content": f"Sorry Sir, the cloud brain hit an error: {e}", "tool": None}

    response = ollama.chat(
        model=MODEL, messages=messages, tools=get_tools_spec(), keep_alive=KEEP_ALIVE
    )
    m = response.message
    content = (m.content or "").strip()
    if m.tool_calls:
        c = m.tool_calls[0].function
        return {"content": content, "tool": (c.name, dict(c.arguments))}
    return {"content": content, "tool": None}


# Most recent tool result, injected into the next single-shot turn so the user
# can refer back to it ("open it", "open the chords", "the second one"). Single-
# shot otherwise forgets tool output between turns, which made follow-ups fail.
_last_result: tuple | None = None


def set_last_result(label: str, content) -> None:
    global _last_result
    text = str(content).strip()
    _last_result = (label, text[:1500]) if text else None


def _system_context() -> str:
    base = get_personality(native_tools=True)
    if _last_result:
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

    messages = [{"role": "system", "content": _system_context()}] + trimmed
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


COMPLEX_SIGNALS = [
    "and then", "after that", "first ", "step by step", "push", "commit", "deploy",
    "research", "find and", "open and", "search and", "write and", "create and",
    "help me", "figure out", "work out", "go to", "navigate to",
    "open chrome and", "sort", "organize", "clean", "tidy", "rename",
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
]


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
    """
    text_lower = message.lower().strip()
    if any(s in text_lower for s in COMPLEX_SIGNALS):
        return True

    if any(s in text_lower for s in SIMPLE_SIGNALS):
        return False

    try:
        response = ollama.chat(
            model=ROUTER_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a routing assistant. Classify the user's request as either 'SIMPLE' or 'COMPLEX'.\n"
                        "- 'SIMPLE': Single-step requests. Opening/closing an app, playing a specific song/movie on Spotify/Netflix directly, asking for date/time, simple questions, simple chit-chat.\n"
                        "- 'COMPLEX': Multi-step requests. Finding and playing a YouTube video (requires searching first), batch file operations (sorting, organizing, cleaning), git tasks (commit, push), command chaining, scripting, research."
                    ),
                },
                {"role": "user", "content": message},
            ],
            format={
                "type": "object",
                "properties": {
                    "classification": {"type": "string", "enum": ["SIMPLE", "COMPLEX"]}
                },
                "required": ["classification"],
            },
            keep_alive=KEEP_ALIVE,
        )
        data = json.loads(response.message.content.strip())
        return data.get("classification") == "COMPLEX"
    except Exception:
        return False  # heuristic already said not-complex; default to single-shot
