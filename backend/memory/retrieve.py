# memory/retrieve.py

import logging
from memory.extractor import extract_names
from memory.writer import MemoryWriter

logger = logging.getLogger("FRIDAY.Memory")

# Words we completely ignore if they are mistakenly flagged as keywords
STOP_WORDS = {
    "where",
    "does",
    "live",
    "who",
    "is",
    "what",
    "the",
    "name",
    "of",
    "my",
    "sister",
    "brother",
    "friend",
    "boss",
    "sir",
    "tell",
    "me",
    "about",
}


def search_memory(query: str, max_triples: int = 25) -> str:
    writer = MemoryWriter()

    try:
        # Step 1 — Extract and normalize entities via GLiNER
        extracted = extract_names(query)
        entities = [name.title() for name in extracted] if extracted else []

        # Step 2 — Advanced Contextual Fallback
        if not entities:
            # Split the query and find any standalone words that aren't stop words
            words = [w.strip(",?.!").lower() for w in query.split()]
            potential_keywords = [
                w.title() for w in words if w not in STOP_WORDS and len(w) > 1
            ]

            if potential_keywords:
                # If "priya" wasn't caught by GLiNER, this catches it as ["Priya"]
                entities = potential_keywords
            else:
                # Absolute last resort for highly ambiguous personal queries
                entities = ["Siddharth"]

        # Step 3 — Fetch active relationships from Neo4j (using case-insensitive fix)
        results = writer.get_active_context(entities)

        if not results:
            return ""

        # Step 4 — Format into pseudo-Cypher Markdown Triples
        lines = []
        for r in results[:max_triples]:
            lines.append(f"({r['source']})-[{r['relation']}]->({r['target']})")

        return "<system_memory>\n" + "\n".join(lines) + "\n</system_memory>"

    except Exception as e:
        logger.error(f"Error executing memory retrieval: {e}")
        return ""

    finally:
        writer.close()
