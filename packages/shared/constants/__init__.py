"""Shared constants — enums, thresholds."""

from __future__ import annotations

from constants.enums import (
    ConfidenceLevel,
    ConsolidationAction,
    MemoryCategory,
    MemoryType,
    ObservationSource,
    RelationshipType,
    ToolName,
)
from constants.thresholds import (
    FACE_EMBEDDING_DIM,
    FACE_KNOWN_THRESHOLD,
    FACE_POSSIBLE_THRESHOLD,
    FRAME_SAMPLE_FPS,
    FUSION_WINDOW_MS,
    GEMINI_AUDIO_CHANNELS,
    GEMINI_AUDIO_SAMPLE_RATE,
    MAX_CONTEXT_AGE_MS,
    OBSERVATION_TTL_MS,
)

__all__ = [
    "ConfidenceLevel",
    "ConsolidationAction",
    "FACE_EMBEDDING_DIM",
    "FACE_KNOWN_THRESHOLD",
    "FACE_POSSIBLE_THRESHOLD",
    "FRAME_SAMPLE_FPS",
    "FUSION_WINDOW_MS",
    "GEMINI_AUDIO_CHANNELS",
    "GEMINI_AUDIO_SAMPLE_RATE",
    "MAX_CONTEXT_AGE_MS",
    "MemoryCategory",
    "MemoryType",
    "OBSERVATION_TTL_MS",
    "ObservationSource",
    "RelationshipType",
    "ToolName",
]
