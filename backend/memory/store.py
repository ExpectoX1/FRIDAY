import asyncio
from concurrent.futures import ThreadPoolExecutor
from memory.extractor import extract_names
from memory.reasoner import reason
from memory.writer import MemoryWriter
from logger import log_system

# shared writer instance
_writer = None
_executor = ThreadPoolExecutor(max_workers=1)


def get_writer() -> MemoryWriter:
    global _writer
    if _writer is None:
        _writer = MemoryWriter()
    return _writer


def _run_pipeline(text: str):
    """Synchronous pipeline — runs in background thread"""
    try:
        writer = get_writer()

        # Step 1 — GLiNER extraction
        entities = extract_names(text)
        log_system("memory", f"GLiNER extracted: {entities}")

        # Step 2 — Neo4j quick read
        current_state = writer.get_active_context(entities)
        log_system("memory", f"Current state: {current_state}")

        # Step 3 — Single Ollama pass
        delta = reason(text, entities, current_state)
        if delta is None:
            return

        # Step 4 — Write to Neo4j
        writer.apply_delta(delta.model_dump())
        log_system("memory", "Memory updated successfully")

    except Exception as e:
        log_system("memory", f"Pipeline error: {e}")


async def store(text: str):
    """Fire and forget — runs pipeline in background thread, never blocks"""
    loop = asyncio.get_event_loop()
    loop.run_in_executor(_executor, _run_pipeline, text)
    log_system("memory", f"Memory pipeline queued for: {text[:50]}")
