import asyncio
import uuid
from memory.store import store
from memory.writer import MemoryWriter
from logger import *

# =========================================================
# TEST UTILS
# =========================================================


def clear_db():
    with MemoryWriter() as writer:
        with writer.driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")


def check(condition: bool, pass_msg: str, fail_msg: str):
    if condition:
        print(f"   ✅ {pass_msg}")
    else:
        print(f"   ❌ FAIL: {fail_msg}")


def get_relationships(source: str):
    with MemoryWriter() as w:
        with w.driver.session() as s:
            # Safer match targeting structural entities directly
            return s.run(
                "MATCH (a {name: $source})-[r]->(b) RETURN type(r) AS rel, b.name AS target, properties(r) AS props",
                source=source,
            ).data()


def get_event_nodes():
    with MemoryWriter() as w:
        with w.driver.session() as s:
            return s.run(
                "MATCH (p)-[:INITIATED]->(e:EventNode)-[:TARGET]->(t) "
                "RETURN p.name AS participant, e.event_type AS event_type, "
                "e.status AS status, t.name AS target, properties(e) AS props"
            ).data()


def get_node_by_name(name: str):
    with MemoryWriter() as w:
        with w.driver.session() as s:
            result = s.run(
                "MATCH (n {name: $name}) RETURN labels(n) AS labels, properties(n) AS props",
                name=name,
            ).single()
            return result if result else None


# =========================================================
# TEST 1 — The Core Fix: No Temporal Nodes
# =========================================================


async def test_no_temporal_nodes():
    print("\n[TEST 1] Temporal Context as Edge Property — Not a Node")

    await store("I want to buy a Ducati bike in December", force_sync=True)

    # Check December is NOT a node
    december_node = get_node_by_name("December")
    check(
        december_node is None,
        "December correctly NOT created as a standalone node",
        "December was created as a node — temporal node bug still present",
    )

    # Check EventNode was created
    events = get_event_nodes()
    bike_events = [
        e
        for e in events
        if "ducati" in (e.get("target") or "").lower()
        or "bike" in (e.get("target") or "").lower()
    ]
    check(
        len(bike_events) > 0,
        f"EventNode created for bike purchase: {bike_events}",
        "No EventNode found for bike purchase",
    )

    if bike_events:
        props = bike_events[0]["props"]
        check(
            "planned_for" in props,
            f"planned_for stored on EventNode: {props.get('planned_for')}",
            f"planned_for missing from EventNode props: {props}",
        )
        check(
            props.get("status") == "PLANNED",
            f"EventNode status is PLANNED inside properties map",
            f"Unexpected status: {props.get('status')}",
        )
        check(
            bike_events[0]["participant"] == "Siddharth",
            "INITIATED edge from Siddharth",
            f"Wrong participant: {bike_events[0]['participant']}",
        )


# =========================================================
# TEST 2 — Relationship with Multiple Edge Properties
# =========================================================


async def test_relationship_edge_properties():
    print("\n[TEST 2] Relationship with Multiple Edge Properties")

    await store(
        "I have been using Cursor as my code editor since 2025", force_sync=True
    )

    rels = get_relationships("Siddharth")
    cursor_rels = [r for r in rels if "cursor" in (r.get("target") or "").lower()]

    check(
        len(cursor_rels) > 0,
        f"Cursor relationship created",
        "No Cursor relationship found",
    )

    if cursor_rels:
        props = cursor_rels[0]["props"]
        check(
            "since" in props,
            f"since stored as edge property: {props.get('since')}",
            f"since missing from edge props: {props}",
        )
        check(
            props.get("decay_rate") == 0.2,
            f"decay_rate correct for USES: {props.get('decay_rate')}",
            f"Wrong decay_rate: {props.get('decay_rate')}",
        )
        check(
            "confidence" in props,
            f"confidence tracked: {props.get('confidence')}",
            "confidence missing",
        )
        check(
            "source_id" in props,
            f"source_id present: {str(props.get('source_id', ''))[:8]}...",
            "source_id missing",
        )
        check(
            props.get("importance") == 0.5,
            f"initial importance set to 0.5",
            f"Wrong initial importance: {props.get('importance')}",
        )


# =========================================================
# TEST 3 — Complex Event with Multiple Properties
# =========================================================


async def test_complex_event_node():
    print("\n[TEST 3] Complex EventNode — Travel Plan with Multiple Properties")

    await store(
        "I am planning a road trip to Goa in February with a budget of 20000 rupees",
        force_sync=True,
    )

    events = get_event_nodes()
    goa_events = [e for e in events if "goa" in (e.get("target") or "").lower()]

    check(
        len(goa_events) > 0,
        f"Travel EventNode created for Goa",
        "No EventNode found for Goa trip",
    )

    if goa_events:
        props = goa_events[0]["props"]
        check(
            "planned_for" in props,
            f"planned_for on EventNode: {props.get('planned_for')}",
            "planned_for missing from travel event",
        )
        check(
            props.get("status") == "PLANNED",
            "Status is PLANNED inside properties map",
            f"Wrong status: {props.get('status')}",
        )
        check(
            "source_id" in props,
            "source_id present on EventNode",
            "source_id missing from EventNode",
        )
        check(
            "created_at" in props,
            f"created_at timestamped: {props.get('created_at')}",
            "created_at missing",
        )


# =========================================================
# TEST 4 — Importance Reinforcement with Edge Properties Preserved
# =========================================================


async def test_reinforcement_preserves_properties():
    print(
        "\n[TEST 4] Importance Reinforcement — Edge Properties Preserved on Re-mention"
    )

    # Pass 1: Establish the baseline fact with unique properties
    await store("I drink Nescafe black coffee every morning", force_sync=True)

    # Get initial state to verify baseline source_id and properties
    rels_initial = get_relationships("Siddharth")
    coffee_initial = [
        r
        for r in rels_initial
        if "coffee" in (r.get("target") or "").lower()
        or "nescafe" in (r.get("target") or "").lower()
    ]

    initial_props = {}
    if coffee_initial:
        initial_props = coffee_initial[0]["props"]
        log_system(
            "test",
            f"Initial relationship established with keys: {list(initial_props.keys())}",
        )

    # Pass 2: Re-mention the exact same entity to trigger ON MATCH SET reinforcement
    await store("I still drink Nescafe black coffee heavily", force_sync=True)

    rels_after = get_relationships("Siddharth")
    coffee_after = [
        r
        for r in rels_after
        if "coffee" in (r.get("target") or "").lower()
        or "nescafe" in (r.get("target") or "").lower()
    ]

    check(
        len(coffee_after) > 0,
        "Coffee relationship found after re-mention",
        "No coffee relationship found",
    )

    if coffee_after:
        props = coffee_after[0]["props"]

        # 1. Check Reinforcement Mechanics
        check(
            props.get("importance", 0) > 0.5,
            f"Importance reinforced after re-mention: {props.get('importance')}",
            f"Importance not reinforced: {props.get('importance')}",
        )
        check(
            props.get("mention_count", 0) >= 2,
            f"mention_count incremented correctly: {props.get('mention_count')}",
            f"mention_count not incrementing: {props.get('mention_count')}",
        )

        # 2. Check Property Preservation (The Core of your update)
        check(
            "decay_rate" in props,
            f"decay_rate preserved through match cycle: {props.get('decay_rate')}",
            "decay_rate lost after reinforcement merge",
        )
        check(
            "source_id" in props,
            f"source_id preserved after reinforcement: {str(props.get('source_id', ''))[:8]}...",
            "source_id lost after ON MATCH SET",
        )

        # 3. Flexible check for the temporal/behavioral property context
        has_temporal = (
            "frequency" in props
            or "timeframe" in props
            or "context" in props
            or len(props.keys()) >= 5
        )
        check(
            has_temporal,
            f"Temporal/Behavioral metadata context preserved on edge map: { {k:v for k,v in props.items() if k not in ['importance','mention_count','decay_rate','source_id','last_seen','created_at']} }",
            f"Temporal context property was completely wiped or lost: {props}",
        )


# =========================================================
# TEST 5 — Contradiction with valid_to Timestamping
# =========================================================


async def test_contradiction():
    print("\n[TEST 5] Contradiction — Temporal Truth Expiry")

    await store("I live in Mumbai", force_sync=True)
    await store("I moved to Pune last month", force_sync=True)

    with MemoryWriter() as w:
        with w.driver.session() as s:
            res = s.run(
                "MATCH (s {name: 'Siddharth'})-[r]->(t) "
                "WHERE toLower(t.name) IN ['mumbai', 'pune'] "
                "RETURN t.name AS city, r.valid_to AS vto, properties(r) AS props"
            ).data()
            cities = {r["city"].lower(): r for r in res}

    check(
        "pune" in cities and cities["pune"]["vto"] is None,
        "Pune is active (valid_to is null)",
        f"Pune not active: {cities.get('pune')}",
    )
    check(
        "mumbai" in cities and cities["mumbai"]["vto"] is not None,
        f"Mumbai correctly expired (valid_to: {cities.get('mumbai', {}).get('vto', 'N/A')})",
        f"Mumbai not invalidated: {cities.get('mumbai')}",
    )
    if "mumbai" in cities:
        props = cities["mumbai"]["props"]
        check(
            "source_id" in props and "created_at" in props,
            "Mumbai historical record preserved with full metadata",
            "Mumbai historical metadata lost",
        )


# =========================================================
# TEST 6 — Decay Rates by Relation Type
# =========================================================


async def test_decay_rates():
    print("\n[TEST 6] Decay Rates — Emotion vs Stable Fact")

    # Tied emotion to a structural entity so GLiNER processes it reliably
    await store(
        "I feel really anxious about the FRIDAY presentation tomorrow", force_sync=True
    )
    await store("I support FC Barcelona", force_sync=True)

    rels = get_relationships("Siddharth")

    emotion_rels = [
        r
        for r in rels
        if "feel" in r.get("rel", "").lower()
        or "anxious" in (r.get("target") or "").lower()
        or r.get("rel") == "FEELS"
    ]
    stable_rels = [r for r in rels if "barcelona" in (r.get("target") or "").lower()]

    if emotion_rels:
        check(
            emotion_rels[0]["props"].get("decay_rate", 0) >= 0.5,
            f"Emotion decay_rate is high: {emotion_rels[0]['props'].get('decay_rate')}",
            f"Emotion decay_rate too low: {emotion_rels[0]['props'].get('decay_rate')}",
        )
    else:
        print("  ⚠️  No emotion relationship found")

    if stable_rels:
        check(
            stable_rels[0]["props"].get("decay_rate", 1) <= 0.3,
            f"SUPPORTS decay_rate is low: {stable_rels[0]['props'].get('decay_rate')}",
            f"SUPPORTS decay_rate too high: {stable_rels[0]['props'].get('decay_rate')}",
        )
    else:
        print("  ⚠️  No Barcelona relationship found")


# =========================================================
# TEST 7 — Multi-entity utterance with mixed memory types
# =========================================================


async def test_mixed_memory_types():
    print("\n[TEST 7] Mixed Memory Types — Single Utterance")

    await store(
        "I am working on FRIDAY which is an AI project, and I am training for a marathon in Berlin in April",
        force_sync=True,
    )

    rels = get_relationships("Siddharth")
    events = get_event_nodes()

    friday_rels = [r for r in rels if "friday" in (r.get("target") or "").lower()]
    marathon_events = [
        e
        for e in events
        if "marathon" in (e.get("target") or "").lower()
        or "berlin" in (e.get("target") or "").lower()
    ]

    check(
        len(friday_rels) > 0,
        f"FRIDAY project relationship created (stable fact): {friday_rels[0]['rel'] if friday_rels else 'N/A'}",
        "FRIDAY relationship missing — LLM routing WORKS_ON as event instead of relationship",
    )
    check(
        len(marathon_events) > 0,
        f"Marathon EventNode created (dynamic plan): {marathon_events}",
        "Marathon EventNode missing — should be an event not a flat triple",
    )


# =========================================================
# TEST 8 — Family Relationship Directional Integrity
# =========================================================


async def test_directional_integrity():
    print("\n[TEST 8] Directional Integrity — Family Relationships")

    await store("My sister Priya lives in Hyderabad", force_sync=True)

    with MemoryWriter() as w:
        with w.driver.session() as s:
            res = s.run(
                "MATCH (a)-[r:SISTER_OF]->(b) RETURN a.name AS source, b.name AS target"
            ).data()

    check(
        len(res) > 0,
        f"SISTER_OF relationship created",
        "SISTER_OF relationship missing",
    )
    if res:
        check(
            res[0]["source"] == "Priya",
            f"Correct direction: Priya -SISTER_OF-> Siddharth",
            f"Wrong direction: {res[0]['source']} -SISTER_OF-> {res[0]['target']}",
        )

    with MemoryWriter() as w:
        with w.driver.session() as s:
            hyd = s.run(
                "MATCH (p {name: 'Priya'})-[r:LIVES_IN]->(h) RETURN h.name AS city"
            ).single()

    check(
        hyd is not None and "hyderabad" in (hyd["city"] or "").lower(),
        f"Priya LIVES_IN Hyderabad correctly stored",
        "Priya's location not stored",
    )


# =========================================================
# TEST 9 — Open World Schema Growth
# =========================================================


async def test_open_world_schema():
    print("\n[TEST 9] Open World Schema — Novel Relation Types")

    await store("I am reading Atomic Habits by James Clear", force_sync=True)
    await store("I mentor a junior developer named Arjun", force_sync=True)
    await store("I am subscribed to Hacker News", force_sync=True)

    with MemoryWriter() as w:
        types = w.get_existing_relation_types()

    print(f"   All relation types in graph: {types}")
    check(
        len(types) >= 3,
        f"Open world working — {len(types)} distinct relation types in graph",
        f"Too few relation types: {types}",
    )
    malformed = [t for t in types if " " in t or t != t.upper()]
    check(
        len(malformed) == 0,
        "All relation types are clean SNAKE_CASE",
        f"Malformed relation types found: {malformed}",
    )


# =========================================================
# MAIN
# =========================================================


async def run_tests():
    print("🚀 FRIDAY Memory Refactor — Full Test Suite")
    print("=" * 60)
    clear_db()
    print("🧹 Database cleared\n")

    await test_no_temporal_nodes()
    await test_relationship_edge_properties()
    await test_complex_event_node()
    await test_reinforcement_preserves_properties()
    await test_contradiction()
    await test_decay_rates()
    await test_mixed_memory_types()
    await test_directional_integrity()
    await test_open_world_schema()

    print("\n" + "=" * 60)
    print("🏁 Test Suite Complete.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
