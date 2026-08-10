"""Gemini schemas — structured-output + tool function declarations."""

from __future__ import annotations

from schemas.extraction import EXTRACTION_SCHEMA
from schemas.tools import (
    ALL_FUNCTION_DECLARATIONS,
    CALENDAR_TOOLS,
    DECLARATIONS_BY_NAME,
    KNOWLEDGE_TOOLS,
    MEMORY_TOOLS,
    OBSERVATION_TOOLS,
    PERSON_TOOLS,
    REMINDER_TOOLS,
    SYSTEM_TOOLS,
    TOOLS_BLOCK,
)

__all__ = [
    "ALL_FUNCTION_DECLARATIONS",
    "CALENDAR_TOOLS",
    "DECLARATIONS_BY_NAME",
    "EXTRACTION_SCHEMA",
    "KNOWLEDGE_TOOLS",
    "MEMORY_TOOLS",
    "OBSERVATION_TOOLS",
    "PERSON_TOOLS",
    "REMINDER_TOOLS",
    "SYSTEM_TOOLS",
    "TOOLS_BLOCK",
]
