"""JSON schemas for Gemini structured output.

Extraction schema → used with client.aio.models.generate_content(config=GenerateContentConfig(
response_mime_type="application/json", response_schema=EXTRACTION_SCHEMA)).
Keeps the extractor output shape in sync with dto.ExtractedKnowledge.
"""

from __future__ import annotations

# knowledge_extraction.md §8 output shape.
EXTRACTION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": [
                            "Person",
                            "Organization",
                            "Place",
                            "Object",
                            "Food",
                            "Event",
                            "Preference",
                            "Relationship",
                            "Reminder",
                            "ShoppingItem",
                        ],
                    },
                    "canonical_name": {"type": "string"},
                },
                "required": ["name", "category"],
            },
        },
        "relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "relationship": {
                        "type": "string",
                        "enum": [
                            "KNOWS",
                            "MET",
                            "WORKS_AT",
                            "LIVES_IN",
                            "LIKES",
                            "DISLIKES",
                            "FRIEND_OF",
                            "FAMILY_OF",
                            "ATTENDS",
                            "LOCATED_AT",
                            "VISITED",
                            "OWNS",
                            "RELATED_TO",
                            "HAS_EVENT",
                            "HAS_REMINDER",
                            "HAS_ITEM",
                            "MENTIONED_IN",
                        ],
                    },
                    "object": {"type": "string"},
                },
                "required": ["subject", "relationship", "object"],
            },
        },
        "facts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Atomic statement strings, e.g. 'Asep works at Tokopedia'.",
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["entities", "relationships", "facts"],
}
