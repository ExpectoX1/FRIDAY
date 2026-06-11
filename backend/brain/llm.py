import ollama
import json
from brain.personality import get_personality

history = []
MAX_HISTORY = 4

# Schema for normal single-shot responses
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["reply", "tool"]},
        "name": {"type": "string"},
        "content": {"type": "string"},
        "args": {"type": "object"},
    },
    "required": ["type"],
}

# Schema for agent loop — includes thought and done signal
AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "type": {"type": "string", "enum": ["reply", "tool"]},
        "name": {"type": "string"},
        "content": {"type": "string"},
        "args": {"type": "object"},
        "done": {"type": "boolean"},
    },
    "required": ["thought", "type"],
}

MODEL = "gemma3:12b"


def normalize_response(data: dict) -> dict:
    from tools.registry import TOOLS

    if data.get("type") in TOOLS:
        return {
            "type": "tool",
            "name": data.get("type"),
            "args": {k: v for k, v in data.items() if k != "type"},
        }
    return data


def clean_json(raw: str) -> str:
    raw = raw.strip()
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()
    raw = raw.replace('"""', '"').replace("'''", "'")
    return raw.strip()


def chat(message: str) -> dict:
    """Single-shot chat — used for simple queries and tool result interpretation."""
    global history
    history.append({"role": "user", "content": message})
    trimmed = history[-MAX_HISTORY:]

    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "system", "content": get_personality()}] + trimmed,
        format=RESPONSE_SCHEMA,
    )

    raw = response.message.content.strip()
    history.append({"role": "assistant", "content": raw})

    try:
        data = json.loads(clean_json(raw))
        return normalize_response(data)
    except json.JSONDecodeError:
        return {"type": "reply", "content": raw}


def agent_chat(message: str, system_override: str = None) -> dict:
    """
    Agent loop chat — uses AGENT_SCHEMA with thought + done fields.
    Does NOT update conversation history (agent steps are internal).
    """
    system = system_override or get_personality()

    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": message},
        ],
        format=AGENT_SCHEMA,
    )

    raw = response.message.content.strip()

    try:
        data = json.loads(clean_json(raw))
        return normalize_response(data)
    except json.JSONDecodeError:
        return {"thought": "Parse error", "type": "reply", "content": raw}


def is_complex(message: str) -> bool:
    """Classifies user utterance as SIMPLE or COMPLEX using the LLM with a keyword fallback."""
    text_lower = message.lower().strip()
    fallback_signals = [
        "and then", "after that", "first ", "step by step", "push", "commit", "deploy",
        "research", "find and", "open and", "search and", "write and", "create and",
        "help me", "figure out", "work out", "can you", "go to", "navigate to",
        "open chrome and", "sort", "organize", "clean", "tidy", "rename"
    ]
    has_fallback_signal = any(s in text_lower for s in fallback_signals)

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a routing assistant. Classify the user's request as either 'SIMPLE' or 'COMPLEX'.\n"
                        "- 'SIMPLE': Single-step requests. Opening/closing an app, playing a specific song/movie on Spotify/Netflix directly, asking for date/time, simple questions, simple chit-chat.\n"
                        "- 'COMPLEX': Multi-step requests. Finding and playing a YouTube video (requires searching first), batch file operations (sorting, organizing, cleaning), git tasks (commit, push), command chaining, scripting, research."
                    )
                },
                {"role": "user", "content": message}
            ],
            format={
                "type": "object",
                "properties": {
                    "classification": {"type": "string", "enum": ["SIMPLE", "COMPLEX"]}
                },
                "required": ["classification"]
            }
        )
        data = json.loads(response.message.content.strip())
        return data.get("classification") == "COMPLEX"
    except Exception:
        return has_fallback_signal
