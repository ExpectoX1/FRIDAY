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
# SKIP PATTERNS — don't store trivial messages
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

CORRECTION_KEYWORDS = ["actually", "meant", "no", "correction", "wait"]

# =========================================================
# HELPERS
# =========================================================


def get_writer() -> MemoryWriter:
    global _writer
    if _writer is None:
        _writer = MemoryWriter()
    return _writer


def is_worth_storing(text: str) -> bool:
    text_lower = text.lower().strip()

    # skip very short messages
    # Allow short messages if they are corrections
    if any(word in text_lower for word in CORRECTION_KEYWORDS):
        return True

    # skip trivial patterns
    if any(text_lower.startswith(p) for p in SKIP_PATTERNS):
        return False

    # skip pure questions — no new facts
    if text_lower.endswith("?"):
        return False

    # skip if GLiNER finds no meaningful entities
    entities = extract_names(text)
    if not entities:
        return False

    return True


# =========================================================
# PIPELINE
# =========================================================


def _run_pipeline(text: str):
    """Synchronous pipeline — runs in background thread or inline"""
    try:
        writer = get_writer()

        # Step 1 — GLiNER extraction
        entities = extract_names(text)
        log_system("memory", f"GLiNER extracted: {entities}")

        if not entities:
            log_system("memory", "No entities found — skipping pipeline")
            return

        # Step 2 — Neo4j quick read
        current_state = writer.get_active_context(entities)
        log_system("memory", f"Current state: {current_state}")

        # Step 3 — Single Ollama pass
        delta = reason(text, entities, current_state)
        if delta is None:
            return

        # Step 4 — Write to Neo4j
        writer.apply_delta(delta.model_dump(), conversation_id=SESSION_CONVERSATION_ID)
        log_system("memory", "Memory updated successfully")

    except Exception as e:
        log_system("memory", f"Pipeline error: {e}")


# =========================================================
# PUBLIC API
# =========================================================


async def store(text: str, force_sync: bool = False):
    """
    Store a conversation entry in memory.
    force_sync=True runs immediately (for testing).
    force_sync=False runs in background thread (for production).
    """
    if not is_worth_storing(text):
        log_system("memory", f"Skipped (not worth storing): {text[:50]}")
        return

    if force_sync:
        _run_pipeline(text)
    else:
        loop = asyncio.get_event_loop()
        loop.run_in_executor(_executor, _run_pipeline, text)
        log_system("memory", f"Memory pipeline queued for: {text[:50]}")
