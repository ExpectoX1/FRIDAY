import time
from gliner import GLiNER

model = GLiNER.from_pretrained("urchade/gliner_medium-v2.1")

ENTITY_LABELS = [
    "person name",
    "family member",
    "city or location",
    "project name",
    "company or sports team",
    "programming language or tool",
    "athlete or player",
    "preference or interest",
    "habit or routine",
    "emotion or feeling",
    "product or brand",
    "date or time",
    "recurring schedule",
    "deadline or event",
    "health or finance fact",
]


# Replace I/my with Siddharth before extraction
def resolve_pronouns(text: str) -> str:
    text = text.replace(" I ", " Siddharth ")
    text = text.replace("I'm", "Siddharth is")
    text = text.replace("I've", "Siddharth has")
    text = text.replace("I'll", "Siddharth will")
    text = text.replace("My ", "Siddharth's ")
    text = text.replace("my ", "Siddharth's ")
    return text


SENTENCES = [
    # People & relationships
    "My sister Priya lives in Mumbai",
    "My friend Alex is a developer at Google",
    "My mum called today, she's not feeling well",
    "I have a meeting with my manager tomorrow",
    # Projects & work
    "I am building FRIDAY, an AI assistant in Python",
    "The cocode project is complete, it was built with React and FastAPI",
    "I need to fix a bug in the executor module",
    "I prefer TypeScript over JavaScript for frontend work",
    # Sports & interests
    "Barcelona lost to Real Madrid last night, I'm devastated",
    "Lewandowski scored a hat trick in the Champions League",
    "I follow YJR on YouTube for football content",
    "The transfer window opens in January",
    # Schedule & habits
    "My standup is every day at 10am",
    "I usually sleep around 2am",
    "I go to the gym every Monday and Thursday",
    "I have a dentist appointment next Friday",
    # Preferences & opinions
    "I love using Cursor for coding, it's better than VSCode",
    "I hate meetings that could have been emails",
    "I prefer dark mode in every app",
    "I think Python is better than Java for AI work",
    # Emotions & wellbeing
    "I'm really stressed about the FRIDAY deadline",
    "I'm excited about the memory system we're building",
    "I haven't slept well this week",
    "I'm feeling much better today",
    # Finance & purchases
    "I'm thinking of buying a MacBook Pro next month",
    "I cancelled my Netflix subscription",
    "I'm saving up for a Royal Enfield bike",
    # Location & travel
    "I live in Bengaluru",
    "I'm visiting Mumbai next week",
    "I want to travel to Japan next year",
]

print(f"Testing {len(SENTENCES)} sentences with {len(ENTITY_LABELS)} labels\n")
print("=" * 60)

total_start = time.time()
missed = []

for sentence in SENTENCES:
    resolved = resolve_pronouns(sentence)
    start = time.time()
    entities = model.predict_entities(resolved, ENTITY_LABELS, threshold=0.5)
    elapsed = (time.time() - start) * 1000

    print(f"\n[{elapsed:.0f}ms] {sentence}")
    if entities:
        for e in entities:
            print(f"  → {e['label']}: {e['text']} ({e['score']:.2f})")
    else:
        print(f"  ❌ NOTHING EXTRACTED")
        missed.append(sentence)

total = time.time() - total_start
print("\n" + "=" * 60)
print(f"Total time: {total:.2f}s")
print(f"Average per sentence: {total/len(SENTENCES)*1000:.0f}ms")
print(f"\nMissed {len(missed)} sentences:")
for m in missed:
    print(f"  - {m}")
