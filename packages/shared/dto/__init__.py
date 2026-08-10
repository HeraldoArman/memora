"""Shared DTOs — observations, memory, knowledge, tools."""

from __future__ import annotations

from dto.knowledge import Entity, ExtractedKnowledge, Relationship
from dto.memory import (
    ContextPackage,
    Fact,
    MemoryRecord,
    Person,
    RankedMemory,
    Reminder,
    RetrievalQuery,
)
from dto.observations import (
    BoundingBox,
    CurrentContext,
    DeviceObservation,
    FaceObservation,
    Observation,
    SceneObservation,
    SpeechObservation,
)
from dto.tools import ToolError, ToolRequest, ToolResponse

__all__ = [
    "BoundingBox",
    "ContextPackage",
    "CurrentContext",
    "DeviceObservation",
    "Entity",
    "ExtractedKnowledge",
    "FaceObservation",
    "Fact",
    "MemoryRecord",
    "Observation",
    "Person",
    "RankedMemory",
    "Relationship",
    "Reminder",
    "RetrievalQuery",
    "SceneObservation",
    "SpeechObservation",
    "ToolError",
    "ToolRequest",
    "ToolResponse",
]
