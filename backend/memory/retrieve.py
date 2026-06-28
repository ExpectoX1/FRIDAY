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
    "status",
    "project",
    "update",
    "current",
    "latest",
}

MIN_ENTITY_LENGTH = 3

# Kinship/relationship edges are stored pointing AT Siddharth, e.g.
# (Priya)-[SISTER_OF]->(Siddharth). Entity-centric search can't reach them
# when the query names no entity ("what is my sister's name"), so we always
# allow these relation types through the Siddharth fallback, on either side.
KINSHIP_RELATIONS = [
    "SISTER_OF",
    "BROTHER_OF",
    "MOTHER_OF",
    "FATHER_OF",
    "SON_OF",
    "DAUGHTER_OF",
    "PARENT_OF",
    "SIBLING_OF",
    "WIFE_OF",
    "HUSBAND_OF",
    "FRIEND_OF",
]

# Maps kinship words a user might say to the stored relation type. Lets the
# relevance check recognise "my sister's name" as relevant to a SISTER_OF edge
# even though the literal word "sister" never appears in the result triples.
KINSHIP_KEYWORDS = {
    "sister": "sister_of",
    "brother": "brother_of",
    "sibling": "sibling_of",
    "mom": "mother_of",
    "mum": "mother_of",
    "mother": "mother_of",
    "dad": "father_of",
    "father": "father_of",
    "son": "son_of",
    "daughter": "daughter_of",
    "parent": "parent_of",
    "wife": "wife_of",
    "husband": "husband_of",
    "friend": "friend_of",
}


# Explicit "nothing found" signal. Returning "" let the model treat empty memory
# as a blank canvas and fabricate (e.g. inventing projects the user doesn't have).
# A clear sentinel tells it memory had nothing, so it admits that or uses other tools.
NO_MEMORY = "No relevant memories found."


def search_memory(query: str, max_triples: int = 25) -> str:
    writer = MemoryWriter()
    try:
        # Step 1 — GLiNER extraction
        extracted = extract_names(query)
        entities = [name.title() for name in extracted] if extracted else []

        # Step 2 — Keyword fallback
        if not entities:
            words = [w.strip(",?.!\"'").lower() for w in query.split()]
            potential = [w.title() for w in words if w not in STOP_WORDS and len(w) > 1]
            entities = potential if potential else []

        # Step 3 — Exact vs fuzzy split
        exact_entities = [e.lower() for e in entities]
        fuzzy_entities = [e.lower() for e in entities if len(e) >= MIN_ENTITY_LENGTH]

        with writer.driver.session() as session:

            # Query 1 — Relationships
            rel_results = session.run(
                """
                MATCH (n)-[r]->(m)
                WHERE (
                    toLower(n.name) IN $exact
                    OR toLower(m.name) IN $exact
                    OR ANY(entity IN $fuzzy WHERE toLower(n.name) CONTAINS entity)
                    OR ANY(entity IN $fuzzy WHERE toLower(m.name) CONTAINS entity)
                    OR (n.name = 'Siddharth' AND type(r) IN ['LIVES_IN', 'WORKS_AT', 'WORKS_ON', 'FEELS'])
                    OR (m.name = 'Siddharth' AND type(r) IN $kinship)
                    OR (n.name = 'Siddharth' AND type(r) IN $kinship)
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
                kinship=KINSHIP_RELATIONS,
                limit=max_triples,
            ).data()

            # Query 2 — EventNodes
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

        # Step 4 — Relevance check
        # If results don't mention any query keywords, return empty
        # This prevents hallucination from unrelated memory context
        if rel_results or event_results:
            query_keywords = set(
                w.lower().strip(",?.!\"'")
                for w in query.split()
                if w.lower() not in STOP_WORDS and len(w) > 2
            )
            all_text = " ".join(
                [
                    str(r.get("source", ""))
                    + str(r.get("relation", ""))
                    + str(r.get("target", ""))
                    for r in rel_results + event_results
                ]
            ).lower()

            # Check if at least one query keyword appears in results
            relevance_hit = any(kw in all_text for kw in query_keywords)

            # Kinship-aware: "my sister's name" should match a SISTER_OF edge
            # even though the literal word "sister" isn't in the triples.
            if not relevance_hit:
                query_lower = query.lower()
                relevance_hit = any(
                    word in query_lower and relation in all_text
                    for word, relation in KINSHIP_KEYWORDS.items()
                )

            if not relevance_hit and query_keywords:
                logger.info(
                    f"Memory results not relevant to query '{query}' — returning empty"
                )
                return NO_MEMORY

        if not rel_results and not event_results:
            return NO_MEMORY

        lines = []

        for r in rel_results:
            lines.append(f"({r['source']})-[{r['relation']}]->({r['target']})")

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
        return NO_MEMORY
    finally:
        writer.close()
