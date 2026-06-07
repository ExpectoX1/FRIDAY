import re
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

    def get_active_context(self, entities: list[str]) -> list[dict]:
        if not entities:
            return []
        query = """
        MATCH (n)-[r]->(m)
        WHERE (n.name IN $entities OR m.name IN $entities)
          AND r.valid_to IS NULL
        RETURN n.name AS source, type(r) AS relation, m.name AS target
        LIMIT 20
        """
        with self.driver.session() as session:
            result = session.run(query, entities=entities)
            return [record.data() for record in result]

    def apply_delta(self, delta: dict):
        with self.driver.session() as session:
            # 1. Invalidate contradictions
            for c in delta.get("contradictions", []):
                rel_type = re.sub(r"[^A-Z_]", "", c["relation"].upper())
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
                # Safely extract string value whether it's an Enum instance or a raw string
                raw_label = (
                    e["label"].value
                    if hasattr(e["label"], "value")
                    else str(e["label"])
                )
                label = re.sub(r"[^A-Za-z]", "", raw_label)
                if not label or "EntityLabel" in label:  # Fallback safety
                    label = "Entity"

                query = f"MERGE (n:{label} {{name: $name}})"
                session.run(query, name=e["name"])
                log_system("memory", f"Entity: {e['name']} ({label})")

            # 3. Create new relationships (Switched to defensive MERGE to protect against drops)
            for r in delta.get("new_relationships", []):
                rel_type = re.sub(r"[^A-Z_]", "", r["relation"].upper())
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
