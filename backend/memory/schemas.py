from pydantic import BaseModel, Field
from typing import Optional, Any
from enum import Enum


class EntityLabel(str, Enum):
    PERSON = "Person"
    LOCATION = "Location"
    PROJECT = "Project"
    ORGANIZATION = "Organization"
    TOOL = "Tool"
    SPORTS_TEAM = "SportsTeam"
    PRODUCT = "Product"
    EVENT = "Event"
    PREFERENCE = "Preference"
    HABIT = "Habit"
    EMOTION = "Emotion"
    ENTITY = "Entity"  # Fallback type


class MemoryType(str, Enum):
    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    EVENT = "EVENT"
    PLAN = "PLAN"
    STATE_CHANGE = "STATE_CHANGE"
    RELATIONSHIP = "RELATIONSHIP"


class EventStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class Entity(BaseModel):
    name: str = Field(description="Normalized name of the entity")
    label: EntityLabel = Field(description="Entity category")


class Relationship(BaseModel):
    source: str = Field(description="Source entity name")
    target: str = Field(description="Target entity name")
    relation: str = Field(
        description="SNAKE_CASE relationship type. Be specific and meaningful e.g. WANTS_TO_BUY, LIVES_IN, USES"
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Arbitrary metadata attributes for the edge. Include temporal context here if mentioned. "
            "Examples: {'valid_from': '2026-06-08', 'planned_for': '2026-12', 'since': '2025', 'confidence': 0.95}"
        ),
    )


class EventNode(BaseModel):
    event_type: str = Field(
        description="SNAKE_CASE classification of the action/plan e.g., ROAD_TRIP, PURCHASE, APP_DEVELOPMENT, RUNNING_RACE"
    )
    status: EventStatus = Field(
        default=EventStatus.PLANNED,
        description="The operational lifecycle state of the event.",
    )
    participants: list[str] = Field(
        default_factory=list,
        description="List of Entity names initiating or involved in the event (e.g., ['Siddharth'])",
    )
    targets: list[str] = Field(
        default_factory=list,
        description="List of Entity names targeted or acted upon by this event (e.g., ['Mumbai', 'bike'])",
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context metadata, such as 'planned_for', 'location', 'price', or 'confidence'.",
    )


class Contradiction(BaseModel):
    source: str
    target: str
    relation: str = Field(description="SNAKE_CASE relation type to invalidate")
    valid_to: str = Field(
        description="ISO-8601 string or YYYY-MM-DD marking when this relationship ceased to be an active truth"
    )


class GraphDelta(BaseModel):
    reasoning: str = Field(
        description="Step-by-step analysis comparing user text against profile baseline and current graph state. Map out memory types, decide if properties or event nodes fit best, and list contradictions."
    )
    memory_type: MemoryType = Field(
        description="Classify the dominant memory type of this entire delta to help direct the database writer."
    )
    new_entities: list[Entity] = Field(default_factory=list)
    new_relationships: list[Relationship] = Field(default_factory=list)
    new_events: list[EventNode] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
