import asyncio
import uuid
from memory.store import store
from memory.writer import MemoryWriter


# =========================================================
# TEST UTILS
# =========================================================


def clear_db():
    with MemoryWriter() as writer:
        with writer.driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")


def get_all_rels(source: str):
    with MemoryWriter() as w:
        with w.driver.session() as s:
            res = s.run(
                "MATCH (a {name: $source})-[r]->(b) RETURN type(r) AS rel, b.name AS target, properties(r) AS props",
                source=source,
            ).data()
            return res


def check(condition: bool, pass_msg: str, fail_msg: str):
    if condition:
        print(f"  ✅ {pass_msg}")
    else:
        print(f"  ⚠️  WARNING: {fail_msg}")


# =========================================================
# TESTS
# =========================================================


async def test_reinforcement():
    print("\n[TEST 1] Importance Reinforcement")
    await store(
        "Siddharth: I love drinking black coffee every morning", force_sync=True
    )
    await store(
        "Siddharth: I really enjoy my black coffee, it is part of my daily routine",
        force_sync=True,
    )

    with MemoryWriter() as w:
        with w.driver.session() as s:
            res = s.run(
                "MATCH (a {name: 'Siddharth'})-[r]->(b) WHERE toLower(b.name) CONTAINS 'coffee' RETURN properties(r) AS props, type(r) AS rel, b.name AS target"
            ).single()

    if res:
        props = dict(res["props"])
        check(
            props.get("importance", 0) > 0.5,
            f"Importance reinforced: {props.get('importance')} (relation: {res['rel']} → {res['target']})",
            f"Importance not reinforced: {props.get('importance')}",
        )
        check(
            props.get("mention_count", 0) >= 2,
            f"Mention count: {props.get('mention_count')}",
            f"Mention count too low: {props.get('mention_count')}",
        )
        check(
            "source_id" in props,
            "Source attribution present",
            "Source attribution missing",
        )
        check(
            "confidence" in props,
            f"Confidence tracked: {props.get('confidence')}",
            "Confidence field missing",
        )
    else:
        print("  ⚠️  WARNING: No coffee-related relationship found")


async def test_contradiction():
    print("\n[TEST 2] Contradiction & Invalidation")
    await store("Siddharth: I live in Mumbai", force_sync=True)
    await store("Siddharth: I moved to Pune last month", force_sync=True)

    with MemoryWriter() as w:
        with w.driver.session() as s:
            res = s.run(
                "MATCH (s {name: 'Siddharth'})-[r]->(t) WHERE toLower(t.name) IN ['mumbai', 'pune'] RETURN t.name AS city, r.valid_to AS vto"
            ).data()
            cities = {r["city"].lower(): r["vto"] for r in res}

    check(
        "pune" in cities and cities["pune"] is None,
        "Pune is active (valid_to is null)",
        f"Pune not found: {cities}",
    )
    check(
        "mumbai" in cities and cities["mumbai"] is not None,
        "Mumbai correctly invalidated",
        f"Mumbai not invalidated: {cities}",
    )


async def test_taxonomy_guard():
    print("\n[TEST 3] Taxonomy Guard — New Relation Discovery")
    await store("Siddharth: I am training for a Marathon in Berlin", force_sync=True)

    with MemoryWriter() as w:
        types = w.get_existing_relation_types()

    training_types = [
        t for t in types if "TRAIN" in t or "LEARN" in t or "PRACTIC" in t
    ]
    check(
        len(training_types) > 0,
        f"Training-type relation created: {training_types}",
        f"No training relation found. Existing types: {types}",
    )


async def test_metadata():
    print("\n[TEST 4] Metadata Attribution")
    await store("Siddharth: I support FC Barcelona", force_sync=True)

    with MemoryWriter() as w:
        with w.driver.session() as s:
            res = s.run(
                "MATCH (s {name: 'Siddharth'})-[r]->(t) WHERE toLower(t.name) CONTAINS 'barcelona' RETURN properties(r) AS props"
            ).single()

    if res:
        props = dict(res["props"])
        check(
            "source_id" in props,
            f"source_id: {props.get('source_id', '')[:8]}...",
            "source_id missing",
        )
        check(
            "confidence" in props,
            f"confidence: {props.get('confidence')}",
            "confidence missing",
        )
        check(
            "decay_rate" in props,
            f"decay_rate: {props.get('decay_rate')}",
            "decay_rate missing",
        )
        check(
            "created_at" in props,
            f"created_at: {props.get('created_at')}",
            "created_at missing",
        )
        check(
            "importance" in props,
            f"importance: {props.get('importance')}",
            "importance missing",
        )
    else:
        print("  ⚠️  WARNING: FC Barcelona relationship not found")


async def test_decay_rates():
    print("\n[TEST 5] Decay Rates by Category")
    await store("Siddharth: I feel stressed about the deadline", force_sync=True)

    with MemoryWriter() as w:
        with w.driver.session() as s:
            res = s.run(
                "MATCH (s {name: 'Siddharth'})-[r]->(t) WHERE type(r) = 'FEELS' OR toLower(type(r)) CONTAINS 'feel' OR toLower(type(r)) CONTAINS 'stress' RETURN properties(r) AS props, type(r) AS rel"
            ).single()

    if res:
        props = dict(res["props"])
        check(
            props.get("decay_rate", 0) >= 0.5,
            f"Emotion decay rate: {props.get('decay_rate')} (rel: {res['rel']})",
            f"Decay rate too low: {props.get('decay_rate')}",
        )
    else:
        print("  ⚠️  WARNING: No emotion relationship found")


async def test_open_world():
    print("\n[TEST 6] Open World Schema")
    await store("Siddharth: I am buying a car in December", force_sync=True)
    await store("Siddharth: I want to travel to Japan next year", force_sync=True)
    await store("Siddharth: I am learning to play guitar", force_sync=True)

    with MemoryWriter() as w:
        types = w.get_existing_relation_types()

    print(f"  All relation types in graph: {types}")
    check(
        len(types) > 3,
        f"Graph has {len(types)} relation types — open world working",
        "Too few relation types",
    )


# =========================================================
# MAIN
# =========================================================


async def run_tests():
    print("🚀 Starting FRIDAY Advanced Memory Lifecycle Tests...")
    print("=" * 60)
    clear_db()
    print("🧹 Database cleared\n")

    await test_reinforcement()
    await test_contradiction()
    await test_taxonomy_guard()
    await test_metadata()
    await test_decay_rates()
    await test_open_world()

    print("\n" + "=" * 60)
    print("🎉 Memory Lifecycle Test Suite Complete.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
