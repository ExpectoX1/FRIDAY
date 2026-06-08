# memory/retrieve.py

from memory.extractor import extract_names
from memory.writer import MemoryWriter
import logging

logger = logging.getLogger("FRIDAY.Memory")

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
    "i",
    "you",
    "he",
    "she",
    "they",
    "we",
    "am",
    "are",
    "do",
    "did",
    "can",
    "how",
    "why",
    "an",
    "a",
    "to",
    "in",
    "for",
    "on",
    "with",
    "usually",
    "just",
    "want",
    "like",
    "get",
    "know",
    "think",
    "please",
}

# Minimum length to protect CONTAINS matching from short token noise
MIN_ENTITY_LENGTH = 3


def search_memory(query: str, max_triples: int = 25) -> str:
    writer = MemoryWriter()
    try:
        # Step 1 — GLiNER extraction
        extracted = extract_names(query)
        entities = [name.title() for name in extracted] if extracted else []

        # Step 2 — Keyword fallback if GLiNER misses
        if not entities:
            words = [w.strip(",?.!\"'").lower() for w in query.split()]
            potential = [w.title() for w in words if w not in STOP_WORDS and len(w) > 1]
            entities = potential if potential else []

        # Step 3 — Segregate exact vs fuzzy entity tokens
        exact_entities = [e.lower() for e in entities]
        fuzzy_entities = [e.lower() for e in entities if len(e) >= MIN_ENTITY_LENGTH]

        with writer.driver.session() as session:

            # Query 1 — Regular relationships
            rel_results = session.run(
                """
                MATCH (n)-[r]->(m)
                WHERE (
                    toLower(n.name) IN $exact
                    OR toLower(m.name) IN $exact
                    OR ANY(entity IN $fuzzy WHERE toLower(n.name) CONTAINS entity)
                    OR ANY(entity IN $fuzzy WHERE toLower(m.name) CONTAINS entity)
                    OR (n.name = 'Siddharth' AND type(r) IN ['LIVES_IN', 'WORKS_AT', 'WORKS_ON', 'FEELS'])
                )
                AND r.valid_to IS NULL
                AND NOT m:EventNode
                AND type(r) <> 'INITIATED'
                AND type(r) <> 'TARGET'
                RETURN n.name AS source, type(r) AS relation, m.name AS target
                LIMIT $limit
            """,
                exact=exact_entities,
                fuzzy=fuzzy_entities,
                limit=max_triples,
            ).data()

            # Query 2 — EventNodes
            # Includes the egocentric baseline rider to capture unanchored future plans
            event_results = session.run(
                """
                MATCH (p)-[:INITIATED]->(e:EventNode)-[:TARGET]->(t)
                WHERE (
                    toLower(p.name) IN $exact
                    OR toLower(t.name) IN $exact
                    OR ANY(entity IN $fuzzy WHERE toLower(p.name) CONTAINS entity)
                    OR ANY(entity IN $fuzzy WHERE toLower(t.name) CONTAINS entity)
                    OR p.name = 'Siddharth'
                )
                RETURN p.name AS source, e.event_type AS relation, t.name AS target,
                       e.status AS status, e.planned_for AS planned_for
                LIMIT $limit
            """,
                exact=exact_entities,
                fuzzy=fuzzy_entities,
                limit=max_triples,
            ).data()

        if not rel_results and not event_results:
            return ""

        lines = []

        # Format standard facts
        for r in rel_results:
            lines.append(f"({r['source']})-[{r['relation']}]->({r['target']})")

        # Format event strings with explicit metadata formatting
        for e in event_results:
            meta = []
            if e.get("planned_for"):
                meta.append(f"planned_for: '{e['planned_for']}'")
            if e.get("status"):
                meta.append(f"status: '{e['status']}'")
            meta_str = f" {{{', '.join(meta)}}}" if meta else ""
            lines.append(
                f"({e['source']})-[{e['relation']}{meta_str}]->({e['target']})"
            )

        return "<system_memory>\n" + "\n".join(lines) + "\n</system_memory>"

    except Exception as e:
        logger.error(f"Memory retrieval error: {e}")
        return ""
    finally:
        writer.close()
