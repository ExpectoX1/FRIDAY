import os
import json
import ollama
from datetime import datetime
from memory.schemas import GraphDelta
from memory.profile import get_profile_prompt
from logger import log_system

# Share the brain model so only ONE big model stays resident. Reads the same
# env var as the brain (brain/llm.py) — loading a different large model here
# evicted the brain and caused multi-second reloads on the next user turn.
MODEL = os.getenv("FRIDAY_LOCAL_MODEL", "qwen3:14b")


def build_prompt(text: str, entities: list[str], current_state: list[dict]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    profile = get_profile_prompt()

    return f"""You are a graph memory extractor. Extract facts from what the user said.

User profile (for context only, DO NOT contradict these unless explicitly changed):
{profile}

User said: "{text}"
Today's Date: {today}

Current active graph relationships for extracted entities:
{json.dumps(current_state, indent=2) if current_state else "EMPTY - no existing relationships found"}

━━━ RULES ━━━

1. If current state is EMPTY, only add to new_entities and new_relationships (or new_events). Never add contradictions.
2. Only add to contradictions if the EXACT relationship exists in current state AND the user explicitly said it changed.
3. Be conservative — only extract facts clearly and explicitly stated. Never infer or hallucinate.
4. Always use "Siddharth" as the source entity EXCEPT for kinship rules (see below).
5. When adding a contradiction, you MUST also add the replacement fact to new_relationships or new_events.

━━━ STRUCTURE ROUTING — MANDATORY ━━━

A single utterance can contain both a stable fact and a complex event simultaneously. You MUST evaluate independent clauses separately and split them across the two arrays. Do not bundle an entire compound sentence into one structure.

Use new_relationships for:
- Stable facts: LIVES_IN, WORKS_ON, USES, SUPPORTS, PREFERS
- Emotions: FEELS
- Habits without a target date: TRAINING_FOR, LEARNING_TO

Use new_events — NO EXCEPTIONS — when an individual clause contains ANY of:
- "want to buy", "wants to buy", "buying", "thinking of buying", "planning to buy"
- "plan to visit", "planning to visit", "road trip to", "traveling to", "going to visit"
- "training for [specific event with date]", "signed up for", "registered for"
- Any purchase intention, travel plan, or goal with a specific deadline/timeframe

COMPOUND EXAMPLES:
Utterance: "I am building FRIDAY and planning a trip to Berlin in April"
✓ RIGHT:
  - new_relationships: (Siddharth)-[WORKS_ON]->(FRIDAY)
  - new_events: event_type=TRAVEL_PLAN, targets=["Berlin"], properties={{"planned_for":"2027-04"}}

HARD EXAMPLES:
✗ WRONG: "I want to buy a bike in December" → new_relationships
✓ RIGHT: "I want to buy a bike in December" → new_events with event_type=PURCHASE, participants=["Siddharth"], targets=["bike"], properties={{"planned_for":"2026-12"}}

✗ WRONG: "I am planning a road trip to Goa in February" → new_relationships
✓ RIGHT: "I am planning a road trip to Goa in February" → new_events with event_type=TRAVEL_PLAN, participants=["Siddharth"], targets=["Goa"], properties={{"planned_for":"2027-02"}}

━━━ TEMPORAL METADATA RULE ━━━

Use Today's Date ({today}) as your temporal anchor. If a user mentions a month without a year, calculate the correct calendar year relative to today.
- If today is June 2026: "December" → "2026-12", "February" → "2027-02", "April" → "2027-04"

NEVER create standalone nodes for: "December", "next week", "every morning", "2025", "February", "April" or ANY time phrase.
Place them inside properties on the relationship or event instead.
✗ WRONG: (Siddharth)-[PLANS_FOR]->(December)
✓ RIGHT: event property {{"planned_for": "2026-12"}}
✓ RIGHT: relationship property {{"frequency": "every morning"}}

━━━ RELATIONSHIP HINTS ━━━
- sister/brother      → SISTER_OF / BROTHER_OF
- lives in/moved to   → LIVES_IN
- supports/fan of     → SUPPORTS
- prefers/uses        → PREFERS / USES
- works on/building   → WORKS_ON
- feels/stressed      → FEELS
- learning/practicing → LEARNING_TO
- habits/routines     → PREFERS with frequency property

━━━ KINSHIP DIRECTIONAL RULE ━━━
Biological reality must be respected. If a phrase introduces a relative (e.g., "My sister Priya lives in Hyderabad"), you MUST extract TWO distinct relationships:
1. The kinship link: source = "Priya", target = "Siddharth", rel = "SISTER_OF"
2. The fact link: source = "Priya", target = "Hyderabad", rel = "LIVES_IN"

- NEVER make Siddharth the source of SISTER_OF, MOTHER_OF, or any female kinship type.
- Kinship phrases like "My friend [Name]" or "My brother [Name]" must ALWAYS generate their explicit descriptive edge alongside any actions they take.

Output JSON delta matching the schema strictly."""


def reason(
    text: str, entities: list[str], current_state: list[dict]
) -> GraphDelta | None:
    prompt = build_prompt(text, entities, current_state)

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            format=GraphDelta.model_json_schema(),
            think=False,  # qwen3: skip chain-of-thought for the structured extract
        )
        raw = response.message.content
        delta = GraphDelta.model_validate_json(raw)
        log_system(
            "memory",
            f"Delta [{delta.memory_type}]: {len(delta.new_entities)} entities, "
            f"{len(delta.new_relationships)} rels, {len(delta.new_events)} events, "
            f"{len(delta.contradictions)} contradictions",
        )
        log_system("memory", f"Reasoning: {delta.reasoning}")
        return delta
    except Exception as e:
        log_system("memory", f"Reasoner failed: {e}")
        return None
