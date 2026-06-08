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

DECAY_RATES = {
    "SISTER_OF": 0.0,
    "BROTHER_OF": 0.0,
    "FATHER_OF": 0.0,
    "MOTHER_OF": 0.0,
    "FRIEND_OF": 0.0,
    "LIVES_IN": 0.0,
    "LOCATED_IN": 0.0,
    "SUPPORTS": 0.2,
    "MEMBER_OF": 0.2,
    "WORKS_AT": 0.2,
    "PREFERS": 0.2,
    "USES": 0.2,
    "DISLIKES": 0.2,
    "WORKS_ON": 0.2,
    "CREATED": 0.2,
    "WANTS_TO_BUY": 0.5,
    "PLANS_TO": 0.5,
    "LEARNING_TO": 0.5,
    "TRAVELING_TO": 0.5,
    "FEELS": 0.8,
    "ATTENDED": 0.8,
    "SCHEDULED_AT": 0.8,
}
DEFAULT_DECAY_RATE = 0.3

# Fields managed exclusively by the writer — never let LLM output overwrite these
SYSTEM_MANAGED_FIELDS = {
    "importance",
    "mention_count",
    "created_at",
    "valid_to",
    "last_seen",
    "valid_from",
}


class MemoryWriter:

    def __init__(self):
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

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

        CANONICAL_TYPES = {
            "SISTER_OF",
            "BROTHER_OF",
            "FATHER_OF",
            "MOTHER_OF",
            "FRIEND_OF",
            "LIVES_IN",
            "LOCATED_IN",
            "SUPPORTS",
            "MEMBER_OF",
            "WORKS_AT",
            "PREFERS",
            "USES",
            "DISLIKES",
            "WORKS_ON",
            "CREATED",
            "WANTS_TO_BUY",
            "PLANS_TO",
            "LEARNING_TO",
            "TRAVELING_TO",
            "FEELS",
            "ATTENDED",
            "SCHEDULED_AT",
            "INITIATED",
            "TARGET",
        }
        if proposed in CANONICAL_TYPES:
            return proposed

        if not existing or proposed in existing:
            return proposed

        prompt = f"""You are a graph taxonomy guard for a personal AI assistant memory system.
            Proposed relation type: {proposed}
            Existing relation types in graph: {existing}

            Rules:
            1. If the proposed type is a clear semantic synonym of an existing type, return the existing type exactly.
            2. If the proposed type is new and distinct, return the proposed type '{proposed}' exactly.
            3. Reply with ONLY the relation type string in SNAKE_CASE. No backticks, no explanations."""

        try:
            response = ollama.chat(
                model="qwen2.5:3b",
                messages=[{"role": "user", "content": prompt}],
            )
            result = re.sub(
                r"[^A-Z_]",
                "",
                response.message.content.strip().upper().replace(" ", "_"),
            )
            return result if result in existing or result == proposed else proposed
        except Exception:
            return proposed

    def get_active_context(self, entities: list[str]) -> list[dict]:
        if not entities:
            return []

        # CRITICAL: Strip generic pronouns so they don't dump the entire DB into the prompt
        PRONOUNS = {"i", "me", "my", "myself", "we", "us", "you"}
        filtered_entities = [e.lower() for e in entities if e.lower() not in PRONOUNS]

        if not filtered_entities:
            return []

        query = """
        MATCH (n)-[r]->(m)
        WHERE (
            toLower(n.name) IN $entities
            OR toLower(m.name) IN $entities
        )
        AND r.valid_to IS NULL
        AND NOT m:EventNode
        AND type(r) <> 'INITIATED'
        AND type(r) <> 'TARGET'
        RETURN n.name AS source, type(r) AS relation, m.name AS target,
            properties(r) AS properties, labels(n) AS source_labels, labels(m) AS target_labels
        LIMIT 30
        """
        with self.driver.session() as session:
            result = session.run(query, entities=filtered_entities)
            return [record.data() for record in result]

    def apply_delta(self, delta: dict, conversation_id: str = None):
        if conversation_id is None:
            conversation_id = str(uuid.uuid4())

        now = datetime.now().isoformat()
        existing_types = self.get_existing_relation_types()

        def get_field(obj, keys, default=None):
            if isinstance(obj, dict):
                for k in keys:
                    if k in obj:
                        return obj[k]
                return default
            for k in keys:
                if hasattr(obj, k):
                    return getattr(obj, k)
            return default

        with self.driver.session() as session:

            # 1. PROCESS CONTRADICTIONS
            for c in get_field(delta, ["contradictions"], []):
                source = get_field(c, ["source"])
                target = get_field(c, ["target"])
                raw_rel = get_field(c, ["relation"])
                valid_to = get_field(c, ["valid_to"]) or now

                rel_type = self.consolidate_relation(raw_rel, existing_types)
                query = f"""
                MATCH (s {{name: $source}})-[r:{rel_type}]->(t {{name: $target}})
                WHERE r.valid_to IS NULL
                SET r.valid_to = $valid_to
                """
                session.run(query, source=source, target=target, valid_to=valid_to)
                log_system(
                    "memory", f"Expired Active Truth: {source} -{rel_type}-> {target}"
                )

            # 2. UPSERT ENTITIES
            for e in get_field(delta, ["new_entities"], []):
                name = get_field(e, ["name"])
                label_obj = get_field(e, ["label"])
                raw_label = (
                    label_obj.value if hasattr(label_obj, "value") else str(label_obj)
                )
                label = re.sub(r"[^A-Za-z]", "", raw_label)
                if not label or "EntityLabel" in label:
                    label = "Entity"
                session.run(f"MERGE (n:{label} {{name: $name}})", name=name)
                log_system("memory", f"Entity Registered: {name} ({label})")

            # 3. UPSERT RELATIONSHIPS
            for r in get_field(delta, ["new_relationships"], []):
                source = get_field(r, ["source"])
                target = get_field(r, ["target"])
                raw_rel = get_field(r, ["relation"])
                props = dict(get_field(r, ["properties"], {}))

                rel_type = self.consolidate_relation(raw_rel, existing_types)
                decay_rate = DECAY_RATES.get(rel_type, DEFAULT_DECAY_RATE)
                confidence = float(props.get("confidence", 0.85))

                # Strip system-managed fields — writer controls these, not the LLM
                for key in SYSTEM_MANAGED_FIELDS:
                    props.pop(key, None)

                # Inject writer-controlled metadata
                props.update(
                    {
                        "decay_rate": decay_rate,
                        "confidence": confidence,
                        "source_id": conversation_id,
                    }
                )

                query = (
                    """
                    MERGE (s {name: $source})
                    MERGE (t {name: $target})
                    MERGE (s)-[rel:%s]->(t)
                    ON CREATE SET
                        rel.valid_from    = $created_at,
                        rel.valid_to      = null,
                        rel.importance    = 0.5,
                        rel.mention_count = 1,
                        rel.created_at    = $created_at
                    ON MATCH SET
                        rel.importance    = CASE WHEN rel.importance + 0.1 > 1.0 THEN 1.0 ELSE rel.importance + 0.1 END,
                        rel.mention_count = coalesce(rel.mention_count, 1) + 1
                    SET rel += $props, rel.last_seen = timestamp()
                    """
                    % rel_type
                )
                session.run(
                    query, source=source, target=target, props=props, created_at=now
                )
                log_system(
                    "memory",
                    f"Edge Written: {source} -{rel_type}-> {target} props={props}",
                )

                if rel_type not in existing_types:
                    existing_types.append(rel_type)

            # 4. GENERATE EVENT NODES
            for ev in get_field(delta, ["new_events"], []):
                e_type = get_field(ev, ["event_type"])
                status_obj = get_field(ev, ["status"])
                status = (
                    status_obj.value
                    if hasattr(status_obj, "value")
                    else str(status_obj)
                )
                participants = get_field(ev, ["participants"], [])
                targets = get_field(ev, ["targets"], [])
                ev_props = dict(get_field(ev, ["properties"], {}))

                event_id = str(uuid.uuid4())
                ev_props.update(
                    {
                        "event_id": event_id,
                        "event_type": e_type,
                        "status": status,
                        "created_at": now,
                        "source_id": conversation_id,
                    }
                )

                session.run("CREATE (e:EventNode $props)", props=ev_props)

                for p_name in participants:
                    session.run(
                        """
                        MERGE (p {name: $p_name})
                        WITH p
                        MATCH (e:EventNode {event_id: $event_id})
                        MERGE (p)-[:INITIATED {valid_from: $now}]->(e)
                        """,
                        p_name=p_name,
                        event_id=event_id,
                        now=now,
                    )

                for t_name in targets:
                    session.run(
                        """
                        MERGE (t {name: $t_name})
                        WITH t
                        MATCH (e:EventNode {event_id: $event_id})
                        MERGE (e)-[:TARGET {valid_from: $now}]->(t)
                        """,
                        t_name=t_name,
                        event_id=event_id,
                        now=now,
                    )

                log_system(
                    "memory",
                    f"Event Node: {e_type} ({status}) {participants} -> {targets}",
                )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
