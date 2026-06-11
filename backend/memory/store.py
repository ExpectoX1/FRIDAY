import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from memory.extractor import extract_names
from memory.reasoner import reason
from memory.writer import MemoryWriter
from logger import log_system

# =========================================================
# GLOBALS
# =========================================================

_writer = None
_executor = ThreadPoolExecutor(max_workers=1)
SESSION_CONVERSATION_ID = str(uuid.uuid4())

# =========================================================
# SKIP PATTERNS
# =========================================================

SKIP_PATTERNS = [
    "hi",
    "hello",
    "hey",
    "bye",
    "goodbye",
    "thanks",
    "thank you",
    "ok",
    "okay",
    "sure",
    "yes",
    "no",
    "what time",
    "open ",
    "close ",
    "exit",
    "quit",
]

CORRECTION_KEYWORDS = ["actually", "meant", "correction", "wait", "no i"]

# Utterances that are never worth storing regardless of entities
NEVER_STORE_PATTERNS = [
    "what time",
    "open ",
    "close ",
    "play ",
    "pause",
    "stop",
    "volume",
    "skip",
    "next",
    "previous",
    "search for",
]

# =========================================================
# HELPERS
# =========================================================


def get_writer() -> MemoryWriter:
    global _writer
    if _writer is None:
        _writer = MemoryWriter()
    return _writer


def check_and_extract_entities(text: str) -> list[str]:
    text_lower = text.lower().strip()

    if any(text_lower.startswith(p) for p in SKIP_PATTERNS) and not any(
        word in text_lower for word in CORRECTION_KEYWORDS
    ):
        return []

    if text_lower.endswith("?"):
        return []

    return extract_names(text)


def _is_worth_storing(text: str) -> bool:
    """
    Fast heuristic gate deciding whether an utterance is worth the full
    memory pipeline. Previously a blocking Gemma call — and because store()
    awaits it on the event loop, that stalled the whole assistant per turn.

    By the time we reach here the utterance has already cleared the pattern
    filter AND yielded GLiNER entities, so it's almost certainly substantive.
    We only need to reject obvious command/control phrasing.
    """
    text_lower = text.lower().strip()
    if any(text_lower.startswith(p) for p in NEVER_STORE_PATTERNS):
        return False
    return True


# =========================================================
# PIPELINE
# =========================================================


def _run_pipeline(text: str, pre_extracted_entities: list[str]):
    try:
        writer = get_writer()
        log_system(
            "memory", f"Running pipeline with entities: {pre_extracted_entities}"
        )

        context_entities = list(set(pre_extracted_entities + ["Siddharth"]))

        current_state = writer.get_active_context(context_entities)
        log_system(
            "memory",
            f"Fetched graph active context state: {len(current_state)} links found",
        )

        delta = reason(text, pre_extracted_entities, current_state)
        if delta is None:
            return

        serialized_delta = delta.model_dump(mode="json")

        writer.apply_delta(serialized_delta, conversation_id=SESSION_CONVERSATION_ID)
        log_system(
            "memory", f"Successfully committed [{delta.memory_type.value}] to graph"
        )

    except Exception as e:
        log_system("memory", f"Pipeline failure: {e}")


# =========================================================
# PUBLIC API
# =========================================================


async def store(text: str, force_sync: bool = False):
    # Step 1 — fast pattern filter
    entities = check_and_extract_entities(text)

    if not entities:
        text_lower = text.lower().strip()
        if any(word in text_lower for word in CORRECTION_KEYWORDS):
            entities = ["Siddharth"]
        else:
            log_system("memory", f"Skipped (pattern): {text[:50]}")
            return

    # Step 2 — fast heuristic filter (no LLM, no event-loop blocking)
    if not _is_worth_storing(text):
        return

    # Step 3 — full pipeline
    if force_sync:
        _run_pipeline(text, entities)
    else:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(_executor, _run_pipeline, text, entities)
        log_system("memory", f"Memory pipeline queued: {text[:50]}")
