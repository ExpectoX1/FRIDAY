from pydantic import BaseModel, Field
from typing import Optional, Literal
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


class Entity(BaseModel):
    name: str = Field(description="Normalized name of the entity")
    label: EntityLabel = Field(description="Entity category")


class Relationship(BaseModel):
    source: str = Field(description="Source entity name")
    target: str = Field(description="Target entity name")
    relation: str = Field(
        description="SNAKE_CASE relationship type. Be specific and meaningful e.g. WANTS_TO_BUY, LEARNING_TO_PLAY, TRAVELING_TO"
    )
    valid_from: Optional[str] = Field(
        None, description="Start date YYYY-MM-DD if mentioned"
    )


class Contradiction(BaseModel):
    source: str
    target: str
    relation: str = Field(description="SNAKE_CASE relation type to invalidate")
    valid_to: Optional[str] = Field(None, description="Date YYYY-MM-DD to invalidate")


class GraphDelta(BaseModel):
    reasoning: str = Field(
        description="Step-by-step analysis comparing user text against profile baseline and current graph state. Map out what new facts to add and what old facts to contradict before filling the arrays."
    )
    new_entities: list[Entity] = Field(default_factory=list)
    new_relationships: list[Relationship] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
