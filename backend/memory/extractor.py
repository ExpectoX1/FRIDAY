import threading
from gliner import GLiNER

_model = None
_lock = threading.Lock()


def get_model() -> GLiNER:
    global _model
    if _model is None:
        with _lock:  # Prevent race conditions during initial load
            if _model is None:
                _model = GLiNER.from_pretrained("urchade/gliner_medium-v2.1")
    return _model


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


def extract(text: str) -> list[dict]:
    model = get_model()
    # Increase threshold slightly to reduce false positives
    entities = model.predict_entities(text, ENTITY_LABELS, threshold=0.6)

    # Return everything so the reasoner can use labels as contextual hints
    return [
        {"text": e["text"], "label": e["label"], "score": e["score"]} for e in entities
    ]


def extract_names(text: str) -> list[str]:
    # Use a dictionary to keep the highest-confidence version of an entity if duplicates exist
    entities = extract(text)
    unique_entities = {}
    for e in entities:
        text_val = e["text"].lower()
        if (
            text_val not in unique_entities
            or e["score"] > unique_entities[text_val]["score"]
        ):
            unique_entities[text_val] = e

    return [e["text"] for e in unique_entities.values()]
