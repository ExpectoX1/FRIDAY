import logging
import re
import uuid
import ollama
from datetime import datetime
from logger import log_system
from neo4j import GraphDatabase

logging.getLogger("neo4j").setLevel(logging.ERROR)

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "friday123"

logger = logging.getLogger("FRIDAY.Memory")

# =========================================================
# DECAY RATES BY RELATION TYPE
# =========================================================

DECAY_RATES = {
    # Identity — never decay
    "SISTER_OF": 0.0,
    "BROTHER_OF": 0.0,
    "FATHER_OF": 0.0,
    "MOTHER_OF": 0.0,
    "FRIEND_OF": 0.0,
    # Location — very slow
    "LIVES_IN": 0.0,
    "LOCATED_IN": 0.0,
    # Affiliations — slow
    "SUPPORTS": 0.2,
    "MEMBER_OF": 0.2,
    "WORKS_AT": 0.2,
    # Preferences — slow
    "PREFERS": 0.2,
    "USES": 0.2,
    "DISLIKES": 0.2,
    # Projects — slow
    "WORKS_ON": 0.2,
    "CREATED": 0.2,
    # Plans/intentions — medium
    "WANTS_TO_BUY": 0.5,
    "PLANS_TO": 0.5,
    "LEARNING_TO": 0.5,
    "TRAVELING_TO": 0.5,
    # Emotions/events — fast
    "FEELS": 0.8,
    "ATTENDED": 0.8,
    "SCHEDULED_AT": 0.8,
}

DEFAULT_DECAY_RATE = 0.3


class MemoryWriter:

    def __init__(self):
        self.driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
        )

    def close(self):
        self.driver.close()

    def get_existing_relation_types(self) -> list[str]:
        try:
            with self.driver.session() as session:
                result = session.run("MATCH ()-[r]->() RETURN DISTINCT type(r) AS rel")
                return [record["rel"] for record in result]
        except Exception as e:
            logger.error(f"Failed to fetch graph taxonomy: {e}")
            return []

    def consolidate_relation(self, proposed: str, existing: list[str]) -> str:
        proposed = re.sub(r"[^A-Z_]", "", proposed.upper().replace(" ", "_"))
        if not proposed:
            return "RELATED_TO"

        if not existing or proposed in existing:
            return proposed

        prompt = f"""You are a graph taxonomy guard for a personal AI assistant memory system.

Proposed relation type: {proposed}
Existing relation types in graph: {existing}

Rules:
1. If the proposed type is semantically equivalent or very similar to an existing one, return the existing one exactly.
2. If it is genuinely different and adds new meaning, return the proposed type as-is.
3. Reply with ONLY the relation type string in SNAKE_CASE. Nothing else, no markdown, no backticks.

Examples:
- PLANNING_TO_BUY vs [WANTS_TO_BUY] → WANTS_TO_BUY
- DISLIKES vs [LIKES, SUPPORTS] → DISLIKES
- LIVES_AT vs [LIVES_IN] → LIVES_IN"""

        try:
            response = ollama.chat(
                model="qwen2.5:3b",
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.message.content.strip()
            cleaned = raw.replace("`", "").replace("'", "").replace('"', "")
            result = re.sub(r"[^A-Z_]", "", cleaned.upper().replace(" ", "_"))

            if result not in existing and result != proposed:
                return proposed

            return result if result else proposed
        except Exception:
            return proposed

    def get_active_context(self, entities: list[str]) -> list[dict]:
        if not entities:
            return []

        lower_entities = [e.lower() for e in entities]

        relationship_keywords = {
            "sister",
            "brother",
            "friend",
            "father",
            "mother",
            "boss",
            "dad",
            "mom",
        }
        has_rel_keyword = any(k in lower_entities for k in relationship_keywords)

        if has_rel_keyword:
            query = """
            MATCH (n)-[r]->(m)
            WHERE (toLower(n.name) IN $entities 
            OR toLower(m.name) IN $entities 
            OR any(k IN $entities WHERE toLower(type(r)) CONTAINS k))
            AND r.valid_to IS NULL
            RETURN n.name AS source, type(r) AS relation, m.name AS target
            LIMIT 20
            """
        else:
            query = """
            MATCH (n)-[r]->(m)
            WHERE (toLower(n.name) IN $entities OR toLower(m.name) IN $entities)
            AND r.valid_to IS NULL
            RETURN n.name AS source, type(r) AS relation, m.name AS target
            LIMIT 20
            """

        with self.driver.session() as session:
            result = session.run(query, entities=lower_entities)
            return [record.data() for record in result]

    def apply_delta(self, delta: dict, conversation_id: str = None):
        if conversation_id is None:
            conversation_id = str(uuid.uuid4())

        now = datetime.now().isoformat()

        # cache existing types once for the whole batch
        existing_types = self.get_existing_relation_types()

        with self.driver.session() as session:

            # 1. Invalidate contradictions
            for c in delta.get("contradictions", []):
                rel_type = self.consolidate_relation(c["relation"], existing_types)
                if not rel_type:
                    continue
                query = f"""
                MATCH (s {{name: $source}})-[r:{rel_type}]->(t {{name: $target}})
                WHERE r.valid_to IS NULL
                SET r.valid_to = $valid_to
                """
                session.run(
                    query,
                    source=c["source"],
                    target=c["target"],
                    valid_to=c.get("valid_to"),
                )
                log_system(
                    "memory", f"Invalidated: {c['source']} -{rel_type}-> {c['target']}"
                )

            # 2. Upsert new entities
            for e in delta.get("new_entities", []):
                raw_label = (
                    e["label"].value
                    if hasattr(e["label"], "value")
                    else str(e["label"])
                )
                label = re.sub(r"[^A-Za-z]", "", raw_label)
                if not label or "EntityLabel" in label:
                    label = "Entity"

                query = f"MERGE (n:{label} {{name: $name}})"
                session.run(query, name=e["name"])
                log_system("memory", f"Entity: {e['name']} ({label})")

            # 3. Create new relationships with full metadata
            for r in delta.get("new_relationships", []):
                rel_type = self.consolidate_relation(r["relation"], existing_types)
                if not rel_type:
                    continue

                decay_rate = DECAY_RATES.get(rel_type, DEFAULT_DECAY_RATE)
                confidence = r.get("confidence", 0.85)

                query = f"""
                MERGE (s {{name: $source}})
                MERGE (t {{name: $target}})
                MERGE (s)-[rel:{rel_type}]->(t)
                ON CREATE SET
                    rel.valid_from = $valid_from,
                    rel.valid_to = null,
                    rel.importance = 0.5,
                    rel.decay_rate = $decay_rate,
                    rel.confidence = $confidence,
                    rel.source_id = $source_id,
                    rel.mention_count = 1,
                    rel.created_at = $created_at,
                    rel.last_seen = timestamp()
                ON MATCH SET
                    rel.importance = CASE
                        WHEN rel.importance + 0.1 > 1.0 THEN 1.0
                        ELSE rel.importance + 0.1 END,
                    rel.mention_count = coalesce(rel.mention_count, 1) + 1,
                    rel.confidence = $confidence,
                    rel.last_seen = timestamp()
                """
                session.run(
                    query,
                    source=r["source"],
                    target=r["target"],
                    valid_from=r.get("valid_from"),
                    decay_rate=decay_rate,
                    confidence=confidence,
                    source_id=conversation_id,
                    created_at=now,
                )
                log_system(
                    "memory",
                    f"Relationship: {r['source']} -{rel_type}-> {r['target']} "
                    f"(importance: 0.5, confidence: {confidence}, decay: {decay_rate})",
                )

                if rel_type not in existing_types:
                    existing_types.append(rel_type)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
