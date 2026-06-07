from gliner import GLiNER

# load once globally
_model = None


def get_model() -> GLiNER:
    global _model
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
    entities = model.predict_entities(text, ENTITY_LABELS, threshold=0.5)
    return [
        {"text": e["text"], "label": e["label"], "score": e["score"]} for e in entities
    ]


def extract_names(text: str) -> list[str]:
    """Returns just the entity text strings for Neo4j lookup"""
    return list(set([e["text"] for e in extract(text)]))
