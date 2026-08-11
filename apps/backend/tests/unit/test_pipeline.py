"""Unit tests — extraction pipeline: filter + runner + consolidator.

Filter is pure rule-based. Runner is tested with fake extractor/consolidator (no LLM,
no DB). Consolidator gets AsyncMock services and exercises REJECT + ACCEPT paths.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from pipeline.consolidator import Consolidator
from pipeline.filter import should_extract
from pipeline.runner import PipelineRunner


class TestShouldExtract:
    def test_none_and_empty(self) -> None:
        assert should_extract(None) is False
        assert should_extract("") is False

    def test_too_short(self) -> None:
        assert should_extract("ya") is False
        assert should_extract("halo") is False

    def test_trivial(self) -> None:
        assert should_extract("apa ini") is False
        assert should_extract("apa itu") is False
        assert should_extract("tidak") is False

    def test_trivial_case_insensitive(self) -> None:
        assert should_extract("APA INI") is False
        assert should_extract("Halo ") is False

    def test_substantive(self) -> None:
        assert should_extract("I'm Asep, I work at Tokopedia, I like sushi") is True
        assert should_extract("   ibu saya suka kopi   ") is True


class _FakeExtractor:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.calls: list[str] = []

    async def extract(self, content: str) -> dict:
        self.calls.append(content)
        return self.result


class TestPipelineRunner:
    async def test_filtered_content_skips_extraction(self) -> None:
        ext = _FakeExtractor({"entities": [], "relationships": []})
        runner = PipelineRunner(extractor=ext, consolidator=AsyncMock())
        out = await runner.run("ya", session_id=None)
        assert out["action"] == "skip"
        assert out["reason"] == "filtered"
        assert ext.calls == []  # no LLM call for trivial content

    async def test_happy_path_calls_both_stages(self) -> None:
        ext = _FakeExtractor(
            {"entities": [{"name": "Asep"}], "relationships": [], "confidence": 0.9}
        )
        cons = AsyncMock()
        cons.consolidate = AsyncMock(
            return_value={"action": "create", "entities": 1, "relationships": 0}
        )
        runner = PipelineRunner(extractor=ext, consolidator=cons)
        out = await runner.run("Asep suka sushi", session_id="s1")
        assert out["action"] == "create"
        assert ext.calls == ["Asep suka sushi"]
        cons.consolidate.assert_awaited_once()
        assert cons.consolidate.await_args.args[0] == ext.result
        assert cons.consolidate.await_args.kwargs == {
            "content": "Asep suka sushi",
            "session_id": "s1",
        }


class TestConsolidator:
    def _cons(self) -> Consolidator:
        c = Consolidator(
            person_service=AsyncMock(),
            knowledge_service=AsyncMock(),
            memory_service=AsyncMock(),
        )
        c.person_service.register_person = AsyncMock(return_value={"person_id": "pid1"})
        c.knowledge_service.upsert_entity = AsyncMock(return_value={})
        c.knowledge_service.add_relation = AsyncMock(return_value={})
        c.memory_service.add_message = AsyncMock(return_value=None)
        c.memory_service.add_facts = AsyncMock(return_value=0)
        return c

    async def test_reject_low_confidence(self) -> None:
        c = self._cons()
        out = await c.consolidate({"confidence": 0.1, "entities": [], "relationships": []})
        assert out["action"] == "reject"
        assert out["entities"] == 0 and out["relationships"] == 0
        c.person_service.register_person.assert_not_called()
        c.memory_service.add_facts.assert_not_called()

    async def test_accept_registers_person_and_adds_relations(self) -> None:
        c = self._cons()
        extraction = {
            "confidence": 0.95,
            "entities": [
                {"name": "Asep", "category": "Person"},
                {"name": "Tokopedia", "category": "Organization"},
                {"name": "sushi", "category": "Food"},
            ],
            "relationships": [
                {"subject": "Asep", "relationship": "WORKS_AT", "object": "Tokopedia"},
                {"subject": "Asep", "relationship": "LIKES", "object": "sushi"},
            ],
            "facts": ["Asep works at Tokopedia"],
        }
        out = await c.consolidate(extraction, content="I'm Asep", session_id=str(uuid4()))
        assert out["action"] == "create"
        assert out["entities"] == 3 and out["relationships"] == 2
        assert out["person_ids"]["Asep"] == "pid1"
        # two relationships: person register called once for entity, then reused
        assert c.person_service.register_person.await_count == 1
        assert c.knowledge_service.add_relation.await_count == 2
        # non-person entities upserted
        cats = [a.kwargs["category"] for a in c.knowledge_service.upsert_entity.await_args_list]
        assert "Preference" in cats  # sushi(Food) → Preference graph category
        # episodic message + facts persisted
        c.memory_service.add_message.assert_awaited_once()
        assert c.memory_service.add_message.await_args.kwargs["content"] == "I'm Asep"
        c.memory_service.add_facts.assert_awaited_once()

    async def test_no_session_no_episode(self) -> None:
        c = self._cons()
        extraction = {
            "confidence": 0.95,
            "entities": [{"name": "Asep", "category": "Person"}],
            "relationships": [],
        }
        await c.consolidate(extraction, content="x", session_id=None)
        c.memory_service.add_message.assert_not_called()

    async def test_relationship_subject_not_in_entities(self) -> None:
        c = self._cons()
        extraction = {
            "confidence": 0.95,
            "entities": [{"name": "Tokopedia", "category": "Organization"}],
            "relationships": [
                {"subject": "Budi", "relationship": "WORKS_AT", "object": "Tokopedia"}
            ],
        }
        out = await c.consolidate(extraction)
        assert out["action"] == "create"
        # Budi auto-registered as Person to host the edge
        assert c.person_service.register_person.await_count == 1
        names = [a.kwargs["name"] for a in c.person_service.register_person.await_args_list]
        assert "Budi" in names
        assert c.knowledge_service.add_relation.await_count == 1

    async def test_missing_rel_fields_skipped(self) -> None:
        c = self._cons()
        extraction = {
            "confidence": 0.95,
            "entities": [{"name": "Asep", "category": "Person"}],
            "relationships": [{"subject": "", "relationship": "", "object": ""}],
        }
        out = await c.consolidate(extraction)
        assert out["action"] == "create"
        c.knowledge_service.add_relation.assert_not_called()

    async def test_single_person_facts_tagged_with_person_id(self) -> None:
        """When exactly one person is identified in the extraction, facts are tagged
        with their person_id — prevents orphan facts when the name is spoken."""
        c = self._cons()
        c.person_service.register_person = AsyncMock(return_value={"person_id": "pid1"})
        extraction = {
            "confidence": 0.9,
            "entities": [{"name": "Asep", "category": "Person"}],
            "relationships": [],
            "facts": ["Asep suka sushi", "Asep kerja di apotek"],
        }
        await c.consolidate(extraction, content="Asep suka sushi", session_id=str(uuid4()))
        c.memory_service.add_facts.assert_awaited_once()
        call = c.memory_service.add_facts.await_args.kwargs
        assert call["person_id"] == "pid1", "facts should be tagged with the single person_id"

    async def test_no_person_facts_orphaned(self) -> None:
        """When no person is identified (unnamed conversation), facts are orphaned
        (person_id=None) — linked retroactively later when the person is identified."""
        c = self._cons()
        extraction = {
            "confidence": 0.7,
            "entities": [{"name": "sushi", "category": "Food"}],
            "relationships": [],
            "facts": ["sushi is delicious"],
        }
        await c.consolidate(extraction, content="sushi is delicious", session_id=str(uuid4()))
        c.memory_service.add_facts.assert_awaited_once()
        call = c.memory_service.add_facts.await_args.kwargs
        assert call.get("person_id") is None, "facts should be orphaned when no person identified"

    async def test_multiple_persons_facts_not_tagged(self) -> None:
        """When multiple persons are identified, facts can't be confidently attributed
        to one — leave them orphaned rather than guessing."""
        c = self._cons()
        c.person_service.register_person = AsyncMock(
            side_effect=[{"person_id": "pid1"}, {"person_id": "pid2"}]
        )
        extraction = {
            "confidence": 0.9,
            "entities": [
                {"name": "Asep", "category": "Person"},
                {"name": "Budi", "category": "Person"},
            ],
            "relationships": [],
            "facts": ["Asep and Budi are friends"],
        }
        await c.consolidate(extraction, content="Asep and Budi", session_id=str(uuid4()))
        c.memory_service.add_facts.assert_awaited_once()
        call = c.memory_service.add_facts.await_args.kwargs
        assert call.get("person_id") is None, "facts should not be tagged with multiple persons"
