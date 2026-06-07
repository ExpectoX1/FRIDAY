import json
import ollama
from datetime import datetime
from memory.schemas import GraphDelta
from memory.profile import get_profile_prompt  # Import your profile tool
from logger import log_system

MODEL = "qwen2.5-coder:14b"
USER_NAME = "Siddharth"


def build_prompt(text: str, entities: list[str], current_state: list[dict]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    profile = get_profile_prompt()

    return f"""You are a graph memory extractor. Extract facts from what the user said.

User profile (for context only, DO NOT contradict these unless explicitly changed):
{profile}

User said: "{text}"
Today: {today}

Current active graph relationships for extracted entities:
{json.dumps(current_state, indent=2) if current_state else "EMPTY - no existing relationships found"}

RULES - follow exactly:
1. If current state is EMPTY, only add to new_entities and new_relationships. Never add contradictions.
2. Only add to contradictions if the EXACT relationship exists in current state above AND the user explicitly said it changed.
3. Always use "Siddharth" as the source entity, never "I", "User", or "user profile".
4. Be conservative — only extract facts clearly and explicitly stated.
5. New facts about activities, goals, events and emotions should ALWAYS be added to new_relationships even if they don't contradict anything.
6. Emotional states should be stored as FEELS relationships e.g. (Siddharth)-[FEELS]->(stressed).
7. Activities and training should be stored e.g. (Siddharth)-[TRAINING_FOR]->(Marathon in Berlin).
8. Intentions and plans should be stored e.g. (Siddharth)-[WANTS_TO_BUY]->(Car).

Relationship mapping hints:
- "sister/brother" → SISTER_OF or BROTHER_OF
- "lives in/moved to" → LIVES_IN
- "supports/fans of" → SUPPORTS
- "prefers/uses/loves" → PREFERS or USES
- "works on/building" → WORKS_ON
- "feels/stressed/excited/happy" → FEELS
- "training/practicing/learning" → TRAINING_FOR or LEARNING_TO
- "wants to/planning to/thinking of buying" → WANTS_TO_BUY or PLANS_TO

CRITICAL DIRECTIONAL RULE:
When extracting family or directional relationships, ensure the subject and object match the biological reality of the text.
- If "A is the sister of B", the source must be the female entity.
- Never make a male subject the source of a SISTER_OF or MOTHER_OF relationship.

Output JSON delta only."""


def reason(
    text: str, entities: list[str], current_state: list[dict]
) -> GraphDelta | None:
    prompt = build_prompt(text, entities, current_state)

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            format=GraphDelta.model_json_schema(),
        )
        raw = response.message.content
        delta = GraphDelta.model_validate_json(raw)
        log_system(
            "memory",
            f"Delta: {len(delta.new_entities)} entities, {len(delta.new_relationships)} relationships, {len(delta.contradictions)} contradictions",
        )
        log_system("memory", f"Reasoning: {delta.reasoning}")
        return delta
    except Exception as e:
        log_system("memory", f"Reasoner failed: {e}")
        return None
