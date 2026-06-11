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
