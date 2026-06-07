import asyncio
from memory.store import store
from memory.writer import MemoryWriter


def clear_db():
    writer = MemoryWriter()
    with writer.driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    writer.close()


def query_graph(source: str, rel_type: str):
    writer = MemoryWriter()
    query = f"MATCH (s {{name: $source}})-[r:{rel_type}]->(t) RETURN t.name as target"
    with writer.driver.session() as session:
        result = session.run(query, source=source)
        data = [record["target"] for record in result]
    writer.close()
    return data


def check(condition: bool, pass_msg: str, fail_msg: str):
    if condition:
        print(f"✅ {pass_msg}")
    else:
        print(f"⚠️  WARNING: {fail_msg}")


async def test():
    print("🚀 Starting FRIDAY Memory Integration Test...")
    clear_db()

    # Step 1: Sister & Location
    await store("My sister Priya lives in Mumbai")
    await asyncio.sleep(20)

    sister_rel = query_graph("Siddharth", "SISTER_OF")
    priya_loc = query_graph("Priya", "LIVES_IN")

    check(
        any("Priya" in r for r in sister_rel),
        "Step 1a: Siddharth -SISTER_OF-> Priya",
        f"SISTER_OF Priya not found, got {sister_rel}",
    )
    check(
        any("Mumbai" in loc for loc in priya_loc),
        "Step 1b: Priya -LIVES_IN-> Mumbai",
        f"LIVES_IN Mumbai not found, got {priya_loc}",
    )

    # Step 2: Support
    await store("I support FC Barcelona")
    await asyncio.sleep(12)

    supports = query_graph("Siddharth", "SUPPORTS")
    check(
        any("FC Barcelona" in s for s in supports),
        "Step 2: Siddharth -SUPPORTS-> FC Barcelona",
        f"SUPPORTS FC Barcelona not found, got {supports}",
    )

    # Step 3: Location Change
    await store("I moved to Pune last month")
    await asyncio.sleep(12)

    locs = query_graph("Siddharth", "LIVES_IN") or query_graph(
        "Siddharth", "LOCATED_IN"
    )
    check(
        any("Pune" in loc for loc in locs),
        "Step 3: Siddharth -LIVES_IN-> Pune",
        f"LIVES_IN/LOCATED_IN Pune not found, got {locs}",
    )

    # Step 4: Tool Preference
    await store("I prefer Neovim over Cursor now")
    await asyncio.sleep(12)

    tools = query_graph("Siddharth", "PREFERS") or query_graph("Siddharth", "USES")
    check(
        any("Neovim" in t for t in tools),
        "Step 4: Siddharth -PREFERS/USES-> Neovim",
        f"PREFERS/USES Neovim not found, got {tools}",
    )

    print("\n🎉 Memory Pipeline Test Complete.")


if __name__ == "__main__":
    asyncio.run(test())
