import re
import ollama
from neo4j import GraphDatabase
from logger import log_system
import logging

logging.getLogger("neo4j").setLevel(logging.ERROR)

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "friday123"


class MemoryWriter:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
        )

    def close(self):
        self.driver.close()

    def get_existing_relation_types(self) -> list[str]:
        """Fetch all relation types currently in the graph"""
        with self.driver.session() as session:
            result = session.run("MATCH ()-[r]->() RETURN DISTINCT type(r) AS rel")
            return [record["rel"] for record in result]

    def consolidate_relation(self, proposed: str) -> str:
        """Map proposed relation to closest existing type or accept as new"""
        proposed = re.sub(r"[^A-Z_]", "", proposed.upper().replace(" ", "_"))
        if not proposed:
            return "RELATED_TO"

        existing = self.get_existing_relation_types()

        if not existing or proposed in existing:
            return proposed

        prompt = f"""You are a graph taxonomy guard for a personal AI assistant memory system.

Proposed relation type: {proposed}
Existing relation types in graph: {existing}

Rules:
1. If the proposed type is semantically equivalent or very similar to an existing one, return the existing one exactly.
2. If it is genuinely different and adds new meaning, return the proposed type as-is.
3. Reply with ONLY the relation type string in SNAKE_CASE. Nothing else.

Examples:
- PLANNING_TO_BUY vs [WANTS_TO_BUY] → WANTS_TO_BUY
- DISLIKES vs [LIKES, SUPPORTS] → DISLIKES (genuinely different)
- LIVES_AT vs [LIVES_IN] → LIVES_IN"""

        try:
            response = ollama.chat(
                model="qwen2.5:3b", messages=[{"role": "user", "content": prompt}]
            )
            result = response.message.content.strip().upper().replace(" ", "_")
            result = re.sub(r"[^A-Z_]", "", result)
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

    def apply_delta(self, delta: dict):
        with self.driver.session() as session:
            # 1. Invalidate contradictions
            for c in delta.get("contradictions", []):
                rel_type = self.consolidate_relation(c["relation"])
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

            # 3. Create new relationships with taxonomy guard
            for r in delta.get("new_relationships", []):
                rel_type = self.consolidate_relation(r["relation"])
                if not rel_type:
                    continue
                query = f"""
                MERGE (s {{name: $source}})
                MERGE (t {{name: $target}})
                MERGE (s)-[rel:{rel_type}]->(t)
                ON CREATE SET rel.valid_from = $valid_from, rel.valid_to = null
                """
                session.run(
                    query,
                    source=r["source"],
                    target=r["target"],
                    valid_from=r.get("valid_from"),
                )
                log_system(
                    "memory", f"Relationship: {r['source']} -{rel_type}-> {r['target']}"
                )
