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


# =========================================================
# PIPELINE
# =========================================================


def _run_pipeline(text: str, pre_extracted_entities: list[str]):
    try:
        writer = get_writer()
        log_system(
            "memory", f"Running pipeline with entities: {pre_extracted_entities}"
        )

        # Always include Siddharth so contradictions and location changes are detectable
        context_entities = list(set(pre_extracted_entities + ["Siddharth"]))

        # Step 1 — Neo4j context read
        current_state = writer.get_active_context(context_entities)
        log_system(
            "memory",
            f"Fetched graph active context state: {len(current_state)} links found",
        )

        # Step 2 — Ollama reasoning
        delta = reason(text, pre_extracted_entities, current_state)
        if delta is None:
            return

        # Step 3 — Serialize (mode=json strips Enum instances to clean strings)
        serialized_delta = delta.model_dump(mode="json")

        # Step 4 — Write to Neo4j
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
    entities = check_and_extract_entities(text)

    if not entities:
        text_lower = text.lower().strip()
        if any(word in text_lower for word in CORRECTION_KEYWORDS):
            entities = ["Siddharth"]
        else:
            log_system("memory", f"Skipped: {text[:50]}")
            return

    if force_sync:
        _run_pipeline(text, entities)
    else:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(_executor, _run_pipeline, text, entities)
        log_system("memory", f"Memory pipeline queued: {text[:50]}")
