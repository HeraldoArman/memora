"""Canonical enums shared across the backend.

Resolved against the PRDs (which disagree across layers):
- MemoryCategory: union of memory_pipeline.md classification table, persistent_storage.md
  Neo4j node types, and knowledge_extraction.md entity types. Food (extraction) is kept
  distinct from Preference (pipeline) — extraction can yield either; consolidation maps Food→Preference.
- RelationshipType: union of persistent_storage.md graph schema + knowledge_extraction.md output.
  ATTENDS chosen over ATTENDED (present tense); LOCATED_AT added (already used in the PRD
  example graph but unlisted in the storage table — PRD omission).
- ToolName: union of tool_api.md (canonical, 22) + reasoning_agent.md extras (create_event,
  search_schedule, shopping_list). register_face ≈ register_person; kept register_person as canonical.
"""

from __future__ import annotations

from enum import StrEnum


class MemoryCategory(StrEnum):
    """What kind of thing a memory/extracted fact is about."""

    PERSON = "Person"
    ORGANIZATION = "Organization"
    PLACE = "Place"
    OBJECT = "Object"
    FOOD = "Food"
    EVENT = "Event"
    PREFERENCE = "Preference"
    RELATIONSHIP = "Relationship"
    REMINDER = "Reminder"
    SHOPPING_ITEM = "ShoppingItem"


class RelationshipType(StrEnum):
    """Neo4j edge labels. Union of storage + extraction lists."""

    KNOWS = "KNOWS"
    MET = "MET"
    WORKS_AT = "WORKS_AT"
    LIVES_IN = "LIVES_IN"
    LIKES = "LIKES"
    DISLIKES = "DISLIKES"
    FRIEND_OF = "FRIEND_OF"
    FAMILY_OF = "FAMILY_OF"
    ATTENDS = "ATTENDS"
    LOCATED_AT = "LOCATED_AT"
    VISITED = "VISITED"
    OWNS = "OWNS"
    RELATED_TO = "RELATED_TO"
    HAS_EVENT = "HAS_EVENT"
    HAS_REMINDER = "HAS_REMINDER"
    HAS_ITEM = "HAS_ITEM"
    MENTIONED_IN = "MENTIONED_IN"


class MemoryType(StrEnum):
    """memory_os.md §12 memory taxonomy."""

    WORKING = "Working"
    EPISODIC = "Episodic"
    SEMANTIC = "Semantic"
    PROCEDURAL = "Procedural"
    PREFERENCE = "Preference"


class ObservationSource(StrEnum):
    """perception.md §11 observation source names."""

    FACE_RECOGNITION = "face_recognition"
    SCENE_UNDERSTANDING = "scene_understanding"
    SPEECH_RECOGNITION = "speech_recognition"
    DEVICE_EVENTS = "device_events"


class ToolName(StrEnum):
    """Gemini Live function-declaration surface. Union of tool_api.md + reasoning_agent.md."""

    # Person
    SEARCH_PERSON = "search_person"
    SEARCH_PERSON_BY_FACE = "search_person_by_face"
    REGISTER_PERSON = "register_person"
    UPDATE_PERSON = "update_person"
    # Memory
    SEARCH_MEMORY = "search_memory"
    RECENT_MEMORIES = "recent_memories"
    SIMILAR_MEMORIES = "similar_memories"
    MEMORY_TIMELINE = "memory_timeline"
    # Reminder
    CREATE_REMINDER = "create_reminder"
    UPDATE_REMINDER = "update_reminder"
    DELETE_REMINDER = "delete_reminder"
    SEARCH_REMINDERS = "search_reminders"
    TODAY_REMINDERS = "today_reminders"
    # Knowledge
    SEARCH_ENTITY = "search_entity"
    ENTITY_RELATIONSHIPS = "entity_relationships"
    SEARCH_PREFERENCES = "search_preferences"
    RELATED_PEOPLE = "related_people"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    # Calendar / shopping (reasoning_agent.md extras)
    CREATE_EVENT = "create_event"
    SEARCH_SCHEDULE = "search_schedule"
    SHOPPING_LIST = "shopping_list"
    # Observation
    CURRENT_SCENE = "current_scene"
    VISIBLE_PEOPLE = "visible_people"
    CURRENT_ACTIVITY = "current_activity"
    CONVERSATION_SUMMARY = "conversation_summary"
    # System
    BATTERY_STATUS = "battery_status"
    NETWORK_STATUS = "network_status"
    DEVICE_INFORMATION = "device_information"
    FIRMWARE_VERSION = "firmware_version"


class ConfidenceLevel(StrEnum):
    """memory_pipeline.md §12 verification outcomes."""

    ACCEPT = "Accept"
    REJECT = "Reject"
    REQUIRE_CONFIRMATION = "Require confirmation"
    LOWER_CONFIDENCE = "Lower confidence"


class ConsolidationAction(StrEnum):
    """memory_pipeline.md Stage 7 / memory_os.md §7 actions."""

    CREATE = "Create"
    UPDATE = "Update"
    MERGE = "Merge"
    ARCHIVE = "Archive"
    CONFLICT = "Conflict"
    IGNORE = "Ignore"
