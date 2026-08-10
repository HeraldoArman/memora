"""Extraction-layer DTOs — knowledge extracted from conversation/context.

knowledge_extraction.md §8 (entity/relationship output), memory_pipeline.md (stages).
The extractor emits ExtractedKnowledge; the pipeline consolidates it into the graph + Postgres.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from constants import ConfidenceLevel, MemoryCategory, RelationshipType
from utils import gen_id, now_utc


class Entity(BaseModel):
    """A recognized entity (person, org, place, object, food, event, ...)."""

    name: str
    category: MemoryCategory
    canonical_name: str | None = None  # after normalization (e.g. "UI" → "Universitas Indonesia")


class Relationship(BaseModel):
    """A directed relationship between two entities."""

    subject: str
    relationship: RelationshipType
    object: str


class ExtractedKnowledge(BaseModel):
    """Output of the KnowledgeExtractor over a CurrentContext snapshot."""

    extraction_id: str = Field(default_factory=gen_id)
    extracted_at: datetime = Field(default_factory=now_utc)
    entities: list[Entity] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)  # raw statement strings
    confidence: float = 0.0
    confidence_level: ConfidenceLevel = ConfidenceLevel.ACCEPT
    source_session_id: str | None = None
