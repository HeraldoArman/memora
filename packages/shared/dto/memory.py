"""Memory-layer DTOs — persons, memories, retrieval, context package.

context.md §11 (Context Package), §15 (provenance), §9 (ranking signals);
memory_os.md §12 (memory types), §15 (provenance).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from constants import MemoryCategory, MemoryType, RelationshipType
from utils import gen_id, now_utc


class Person(BaseModel):
    """A known person in the graph (Neo4j node + FAISS embedding sidecar)."""

    person_id: str = Field(default_factory=gen_id)
    name: str
    notes: str | None = None
    embedding_registered: bool = False  # True once a FAISS vector is linked
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class Fact(BaseModel):
    """A single atomic assertion: subject -relationship-> object (or a standalone fact)."""

    fact_id: str = Field(default_factory=gen_id)
    subject: str
    relationship: RelationshipType | None = None
    object: str | None = None
    statement: str  # human-readable, e.g. "Asep works at Tokopedia"
    category: MemoryCategory
    confidence: float = 0.0


class MemoryRecord(BaseModel):
    """An episodic/semantic memory with full provenance (memory_os.md §15)."""

    memory_id: str = Field(default_factory=gen_id)
    memory_type: MemoryType = MemoryType.EPISODIC
    content: str  # the remembered statement
    category: MemoryCategory = MemoryCategory.PERSON
    confidence: float = 0.0
    # Provenance
    source_conversation_id: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    related_people: list[str] = Field(default_factory=list)
    related_observations: list[str] = Field(default_factory=list)  # observation_ids
    archived: bool = False


class RetrievalQuery(BaseModel):
    """Query into the memory store (Neo4j + Postgres + FAISS)."""

    query: str
    person_id: str | None = None  # restrict to a person's subgraph
    location: str | None = None
    top_k: int = 10
    memory_types: list[MemoryType] = Field(default_factory=list)


class RankedMemory(BaseModel):
    """A memory hit with a ranking score (context.md §9 signals)."""

    memory: MemoryRecord
    score: float = 0.0
    # individual signal contributions (for explainability)
    signals: dict[str, float] = Field(default_factory=dict)


class ContextPackage(BaseModel):
    """Structured context delivered to the reasoning agent (context.md §11).

    Structured rather than free-form text per the PRD. Each fact carries provenance.
    """

    location: str | None = None
    visible_people: list[str] = Field(default_factory=list)
    relevant_facts: list[Fact] = Field(default_factory=list)
    conversation_history: list[str] = Field(default_factory=list)
    upcoming_reminders: list[str] = Field(default_factory=list)
    user_question: str | None = None
    device_context: str | None = None
    # Provenance for each fact (context.md §15): memory_id → provenance
    provenance: dict[str, dict] = Field(default_factory=dict)
    assembled_at: datetime = Field(default_factory=now_utc)


class Reminder(BaseModel):
    """Reminder DTO (mirrors the Postgres reminder row)."""

    reminder_id: str = Field(default_factory=gen_id)
    title: str
    note: str | None = None
    due_at: datetime | None = None
    completed: bool = False
    created_at: datetime = Field(default_factory=now_utc)
