import ollama
import json
from brain.personality import get_personality
from tools.registry import get_tools_spec

history = []
MAX_HISTORY = 4

MODEL = "gemma4:latest"  # supports native Ollama tool calling (gemma3 does not)
ROUTER_MODEL = "qwen2.5:3b"  # small/fast model for SIMPLE/COMPLEX routing

# Keep models resident between calls. We alternate brain (gemma4) and router
# (qwen3b) every turn; without this, Ollama can evict one to load the other,
# paying a multi-second reload each time. A long TTL pins both warm.
KEEP_ALIVE = "30m"


def chat(message: str) -> dict:
    """Single-shot chat — used for simple queries and tool result interpretation.

    Uses native Ollama tool calling: the model either emits a structured
    tool_call or returns plain text. No more JSON-in-text parsing.
    """
    global history
    history.append({"role": "user", "content": message})
    trimmed = history[-MAX_HISTORY:]

    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "system", "content": get_personality(native_tools=True)}]
        + trimmed,
        tools=get_tools_spec(),
        keep_alive=KEEP_ALIVE,
    )

    msg = response.message

    if msg.tool_calls:
        call = msg.tool_calls[0].function
        # Record the assistant's tool intent in history for continuity.
        history.append(
            {"role": "assistant", "content": f"[called {call.name}]"}
        )
        return {
            "type": "tool",
            "name": call.name,
            "args": dict(call.arguments),
        }

    content = (msg.content or "").strip()
    history.append({"role": "assistant", "content": content})
    return {"type": "reply", "content": content}


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
    response = ollama.chat(
        model=MODEL,
        messages=messages,
        tools=get_tools_spec(),
        keep_alive=KEEP_ALIVE,
    )

    msg = response.message
    thought = (msg.content or "").strip()

    if msg.tool_calls:
        call = msg.tool_calls[0].function
        args = dict(call.arguments)
        # Plain-dict form of the assistant turn so `messages` stays fully
        # JSON-serializable (it gets stored in pending_state and logged).
        raw_message = {
            "role": "assistant",
            "content": thought,
            "tool_calls": [{"function": {"name": call.name, "arguments": args}}],
        }
        return {
            "type": "tool",
            "name": call.name,
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
