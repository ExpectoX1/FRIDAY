import asyncio
import time
from datetime import datetime
from gliner import GLiNER
from memory.graphiti_client import get_graphiti

# =========================================================
# GLINER SETUP
# =========================================================

ner_model = GLiNER.from_pretrained("urchade/gliner_medium-v2.1")

ENTITY_LABELS = [
    "person name",
    "family member",
    "city or location",
    "project name",
    "company or sports team",
    "programming language or tool",
    "software component or module",
    "athlete or player",
    "preference or interest",
    "habit or behavior",
    "emotion or feeling",
    "product or brand",
    "date or time",
    "recurring schedule",
    "deadline or event",
    "health or finance fact",
]

USER_NAME = "Siddharth"


def extract_entities(text: str) -> list:
    entities = ner_model.predict_entities(text, ENTITY_LABELS, threshold=0.5)
    return entities


def enrich_episode(text: str, entities: list) -> str:
    entity_str = ", ".join([f"{e['text']} ({e['label']})" for e in entities])
    enriched = f"[User: {USER_NAME}] {text}"
    if entities:
        enriched += f"\n[Entities: {entity_str}]"
    return enriched


# =========================================================
# TEST
# =========================================================


async def test():
    g = get_graphiti()
    await g.build_indices_and_constraints()

    episodes = [
        "My sister Priya lives in Mumbai and is visiting next week",
        "I support FC Barcelona, they are my favourite football club",
        "I am building a project called FRIDAY which is an AI assistant",
        "I prefer Python and TypeScript for development",
        "My standup meeting is every day at 10am",
        "I am stressed about the FRIDAY deadline",
        "I live in Bengaluru",
        "I am thinking of buying a Royal Enfield bike in December",
    ]

    total_store_start = time.time()

    for i, episode in enumerate(episodes):
        start = time.time()

        ner_start = time.time()
        entities = extract_entities(episode)
        ner_elapsed = (time.time() - ner_start) * 1000

        enriched = enrich_episode(episode, entities)

        print(f"\nStoring: {episode[:50]}...")
        print(
            f"  GLiNER ({ner_elapsed:.0f}ms): {[(e['text'], e['label']) for e in entities]}"
        )
        print(f"  Enriched: {enriched[:100]}")

        await g.add_episode(
            name=f"hybrid_{i:03d}",
            episode_body=enriched,
            source_description="voice conversation",
            reference_time=datetime.now(),
        )

        elapsed = time.time() - start
        print(f"  ✓ Total: {elapsed:.2f}s")

    total_store = time.time() - total_store_start
    print(f"\nTotal store time: {total_store:.2f}s")
    print(f"Average per episode: {total_store/len(episodes):.2f}s")

    print("\n" + "=" * 60)
    print("SEARCHING MEMORY")
    print("=" * 60)

    for query in ["sister", "football", "Barcelona", "project", "bike", "location"]:
        start = time.time()
        results = await g.search(query)
        elapsed = time.time() - start
        print(f"\nSearch '{query}' ({elapsed:.2f}s): {len(results.edges)} results")
        for r in results.edges[:2]:
            print(f"  - {r.fact}")

    await g.close()


asyncio.run(test())
