"""Unit tests — shared DTOs, constants, schemas, utils (packages/shared).

Pure-Python, no DB/network. Every DTO default + validator, every enum member
that's wired into the tool surface, and the util helpers.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from constants import (
    ConfidenceLevel,
    ConsolidationAction,
    MemoryCategory,
    MemoryType,
    ObservationSource,
    RelationshipType,
    ToolName,
)
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
    CurrentContext,
    DeviceObservation,
    FaceObservation,
    SceneObservation,
    SpeechObservation,
)
from dto.tools import ToolError, ToolRequest, ToolResponse
from utils import aggregate_confidence, gen_id, iso_now, now_utc


class TestUtils:
    def test_gen_id_hex_unique(self) -> None:
        a, b = gen_id(), gen_id()
        assert a != b and len(a) == 32
        assert all(c in "0123456789abcdef" for c in a)

    def test_now_utc_aware(self) -> None:
        dt = now_utc()
        assert dt.tzinfo is not None

    def test_iso_now(self) -> None:
        assert "T" in iso_now()

    def test_aggregate_confidence_default_weights(self) -> None:
        assert aggregate_confidence([0.5, 0.9]) == pytest.approx(0.7)

    def test_aggregate_confidence_weighted(self) -> None:
        assert aggregate_confidence([0.4, 0.8], weights=[3, 1]) == pytest.approx(0.5)

    def test_aggregate_confidence_empty(self) -> None:
        assert aggregate_confidence([]) == 0.0

    def test_aggregate_confidence_zero_total_weights(self) -> None:
        assert aggregate_confidence([0.9, 0.8], weights=[0, 0]) == 0.0

    def test_aggregate_confidence_length_mismatch(self) -> None:
        with pytest.raises(ValueError):
            aggregate_confidence([0.9], weights=[0.5, 0.5])


class TestObservationDtos:
    def test_observation_defaults(self) -> None:
        obs = SpeechObservation(transcript="halo")
        assert obs.source == ObservationSource.SPEECH_RECOGNITION
        assert obs.observation_id and obs.timestamp is not None
        assert obs.is_final is True and obs.language == "id"

    def test_face_observation_known(self) -> None:
        f = FaceObservation(person_id="p1", name="Asep", is_known=True, confidence=0.95)
        assert f.source == ObservationSource.FACE_RECOGNITION
        assert f.is_known and f.name == "Asep"

    def test_face_observation_embedding(self) -> None:
        import numpy as np

        emb = np.zeros(512, dtype=np.float32)
        f = FaceObservation(embedding=emb)
        assert f.embedding is emb  # arbitrary_types_allowed passthrough

    def test_scene_observation(self) -> None:
        s = SceneObservation(location="apotek", objects=["rak"], activity="beli obat")
        assert s.source == ObservationSource.SCENE_UNDERSTANDING
        assert s.objects == ["rak"]

    def test_device_observation_defaults(self) -> None:
        d = DeviceObservation()
        assert d.battery_level is None and d.wifi_connected and not d.button_pressed

    def test_current_context_defaults(self) -> None:
        ctx = CurrentContext()
        assert ctx.visible_people == [] and ctx.scene is None and ctx.speech is None
        assert ctx.confidence == 0.0 and ctx.observations == []

    def test_current_context_round_trip(self) -> None:
        ctx = CurrentContext(
            visible_people=["Asep"],
            scene="apotek",
            observations=[SpeechObservation(transcript="halo")],
        )
        assert ctx.model_dump()["visible_people"] == ["Asep"]
        assert ctx.observations[0].transcript == "halo"

    def test_speech_requires_transcript(self) -> None:
        with pytest.raises(ValidationError):
            SpeechObservation()  # type: ignore[call-arg]


class TestKnowledgeDtos:
    def test_entity_defaults(self) -> None:
        e = Entity(name="Tokopedia", category=MemoryCategory.ORGANIZATION)
        assert e.canonical_name is None and e.category == "Organization"

    def test_extracted_knowledge_defaults(self) -> None:
        k = ExtractedKnowledge()
        assert k.entities == [] and k.confidence == 0.0
        assert k.confidence_level == ConfidenceLevel.ACCEPT

    def test_relationship_validates_type(self) -> None:
        r = Relationship(subject="Asep", relationship=RelationshipType.WORKS_AT, object="Tokopedia")
        assert r.relationship == "WORKS_AT"

    def test_entity_invalid_category(self) -> None:
        with pytest.raises(ValidationError):
            Entity(name="X", category="Nope")  # type: ignore[arg-type]


class TestMemoryDtos:
    def test_person_defaults(self) -> None:
        p = Person(name="Asep")
        assert p.person_id and not p.embedding_registered

    def test_memory_record_defaults(self) -> None:
        m = MemoryRecord(content="ingatan")
        assert m.memory_type == MemoryType.EPISODIC
        assert not m.archived

    def test_retrieval_query_defaults(self) -> None:
        q = RetrievalQuery(query="dimana")
        assert q.top_k == 10 and q.memory_types == []

    def test_ranked_memory(self) -> None:
        rm = RankedMemory(memory=MemoryRecord(content="x"), score=0.9, signals={"temporal": 0.4})
        assert rm.score == 0.9 and rm.signals["temporal"] == 0.4

    def test_context_package_defaults(self) -> None:
        cp = ContextPackage()
        assert cp.visible_people == [] and cp.relevant_facts == [] and cp.provenance == {}

    def test_reminder_defaults(self) -> None:
        r = Reminder(title="minum obat")
        assert not r.completed and r.due_at is None

    def test_fact_defaults(self) -> None:
        f = Fact(subject="Asep", statement="Asep suka sushi", category=MemoryCategory.PREFERENCE)
        assert f.relationship is None and f.confidence == 0.0


class TestToolDtos:
    def test_tool_request_defaults(self) -> None:
        req = ToolRequest(name=ToolName.SEARCH_PERSON)
        assert req.parameters == {} and req.call_id

    def test_tool_response_ok(self) -> None:
        r = ToolResponse(call_id="c1", result={"name": "Asep"})
        assert r.ok and r.error is None

    def test_tool_response_error(self) -> None:
        r = ToolResponse(call_id="c1", ok=False, error=ToolError(code="not_found", message="x"))
        assert not r.ok and r.error.code == "not_found"

    def test_tool_request_invalid_name(self) -> None:
        with pytest.raises(ValidationError):
            ToolRequest(name="no_such_tool")  # type: ignore[arg-type]


class TestEnums:
    def test_tool_name_covers_full_surface(self) -> None:
        from schemas import ALL_FUNCTION_DECLARATIONS

        declared = {d["name"] for d in ALL_FUNCTION_DECLARATIONS}
        assert declared == {t.value for t in ToolName}, (
            "ToolName enum and declarations must stay in sync"
        )

    def test_relationship_type_values(self) -> None:
        assert RelationshipType.WORKS_AT.value == "WORKS_AT"
        assert len(RelationshipType) == 17

    def test_memory_category_values(self) -> None:
        assert MemoryCategory.FOOD.value == "Food"
        assert len(MemoryCategory) == 10

    def test_consolidation_action(self) -> None:
        assert {a.value for a in ConsolidationAction} == {
            "Create",
            "Update",
            "Merge",
            "Archive",
            "Conflict",
            "Ignore",
        }

    def test_observation_source_values(self) -> None:
        assert ObservationSource.DEVICE_EVENTS.value == "device_events"


class TestSchemas:
    def test_extraction_schema_shape(self) -> None:
        from schemas import EXTRACTION_SCHEMA

        assert EXTRACTION_SCHEMA["type"] == "object"
        assert set(EXTRACTION_SCHEMA["required"]) == {"entities", "relationships", "facts"}

    def test_extraction_schema_enum_matches_constants(self) -> None:
        from schemas import EXTRACTION_SCHEMA

        cat_enum = EXTRACTION_SCHEMA["properties"]["entities"]["items"]["properties"]["category"][
            "enum"
        ]
        assert set(cat_enum) == {c.value for c in MemoryCategory}

    def test_tools_block(self) -> None:
        from schemas import TOOLS_BLOCK

        names = [d["name"] for d in TOOLS_BLOCK["function_declarations"]]
        assert "current_scene" in names and "register_face" in names and "shopping_list" in names
        assert len(names) == len(set(names))  # no dupes
