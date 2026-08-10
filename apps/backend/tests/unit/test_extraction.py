"""Unit tests — extraction stages: classifier, normalizer, resolver, verifier, extractor.

The first four are pure rules (no LLM). The extractor's `extract` is tested with a fake
client: happy path, empty-content short-circuit, and API-failure graceful degradation.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from constants import ConfidenceLevel, MemoryCategory
from extraction.classifier import classify, for_graph
from extraction.extractor import KnowledgeExtractor, _empty, _normalize, _parse
from extraction.normalizer import normalize
from extraction.resolver import is_alias, resolve_batch, resolve_name
from extraction.verifier import accepted, verify


class TestClassifier:
    def test_valid_categories(self) -> None:
        assert classify("Person") is MemoryCategory.PERSON
        assert classify("Organization") is MemoryCategory.ORGANIZATION
        assert classify("Food") is MemoryCategory.FOOD
        assert classify("Reminder") is MemoryCategory.REMINDER

    def test_invalid_falls_back_by_name(self) -> None:
        assert classify("Bogus", name="Asep") is MemoryCategory.PERSON
        assert classify(None, name="Tokopedia") is MemoryCategory.PERSON
        assert classify("Bogus", name="sushi") is MemoryCategory.OBJECT

    def test_none_name_object(self) -> None:
        assert classify(None) is MemoryCategory.OBJECT
        assert classify("Bogus") is MemoryCategory.OBJECT

    def test_for_graph_food_to_preference(self) -> None:
        assert for_graph(MemoryCategory.FOOD) is MemoryCategory.PREFERENCE
        assert for_graph(MemoryCategory.PERSON) is MemoryCategory.PERSON
        assert for_graph(MemoryCategory.ORGANIZATION) is MemoryCategory.ORGANIZATION


class TestNormalizer:
    def test_canonical_expansions(self) -> None:
        assert normalize("ui") == "Universitas Indonesia"
        assert normalize("UI") == "Universitas Indonesia"
        assert normalize("rs") == "Rumah Sakit"
        assert normalize("  tokped ") == "Tokopedia"
        assert normalize("KTP") == "Kartu Tanda Penduduk"

    def test_title_case(self) -> None:
        assert normalize("asep") == "Asep"
        assert normalize("Muhammad Asep") == "Muhammad Asep"

    def test_acronyms_preserved(self) -> None:
        assert normalize("BPJS") == "BPJS Kesehatan"  # canonical wins
        assert normalize("UI") == "Universitas Indonesia"

    def test_whitespace_collapse(self) -> None:
        assert normalize("  Asep   Surya  ") == "Asep Surya"

    def test_empty(self) -> None:
        assert normalize("") == ""
        assert normalize(None) is None


class TestResolver:
    def test_honorific_strip(self) -> None:
        assert resolve_name("Bang Asep") == "Asep"
        assert resolve_name("Pak Asep") == "Asep"
        assert resolve_name("Mas Budi") == "Budi"
        assert resolve_name("Muhammad Asep") == "Muhammad Asep"  # not an honorific

    def test_resolve_batch_dedup(self) -> None:
        m = resolve_batch(["Bang Asep", "Asep", "Tokopedia"])
        assert m["Bang Asep"] == m["Asep"] == "Asep"
        assert m["Tokopedia"] == "Tokopedia"

    def test_is_alias(self) -> None:
        assert is_alias("Bang Asep", "Asep") is True
        assert is_alias("Pak Asep", "Asep") is True
        assert is_alias("Muhammad Asep", "Muhammad Asep") is True
        assert is_alias("Asep", "Budi") is False
        assert is_alias("Asep", "Tokopedia") is False

    def test_is_alias_shared_surname(self) -> None:
        # same first+last token → likely same person
        assert is_alias("Asep Surya", "Asep Surya") is True


class TestVerifier:
    def test_levels(self) -> None:
        assert verify(0.9) is ConfidenceLevel.ACCEPT
        assert verify(0.6) is ConfidenceLevel.LOWER_CONFIDENCE
        assert verify(0.3) is ConfidenceLevel.REJECT

    def test_first_person_boost(self) -> None:
        assert verify(0.8, content="I'm Asep") is ConfidenceLevel.ACCEPT  # 0.8 → 0.9
        assert verify(0.8, content="aku suka sushi") is ConfidenceLevel.ACCEPT
        assert verify(0.8, content="apa ini?") is ConfidenceLevel.LOWER_CONFIDENCE

    def test_boost_capped(self) -> None:
        assert verify(0.99, content="I'm Asep") is ConfidenceLevel.ACCEPT

    def test_accepted(self) -> None:
        assert accepted(ConfidenceLevel.ACCEPT) is True
        assert accepted(ConfidenceLevel.LOWER_CONFIDENCE) is True
        assert accepted(ConfidenceLevel.REJECT) is False


class TestExtractorParse:
    def test_empty(self) -> None:
        assert _empty() == {"entities": [], "relationships": [], "facts": [], "confidence": 0.0}

    def test_normalize_defaults(self) -> None:
        assert _normalize({}) == _empty()
        assert _normalize({"confidence": 0.9})["confidence"] == 0.9
        assert _normalize({"entities": None})["entities"] == []

    def test_parse_parsed_dict(self) -> None:
        resp = type(
            "R",
            (),
            {"parsed": {"entities": [], "relationships": [], "facts": [], "confidence": 0.5}},
        )
        assert _parse(resp)["confidence"] == 0.5

    def test_parse_text_json(self) -> None:
        resp = type("R", (), {"parsed": None, "text": json.dumps({"entities": [], "facts": []})})
        out = _parse(resp)
        assert out["entities"] == [] and out["facts"] == []

    def test_parse_empty_text(self) -> None:
        resp = type("R", (), {"parsed": None, "text": ""})
        assert _parse(resp) == _empty()

    def test_parse_bad_json_raises(self) -> None:
        resp = type("R", (), {"parsed": None, "text": "not json"})
        with pytest.raises(json.JSONDecodeError):
            _parse(resp)


class _FakeModels:
    def __init__(self, client) -> None:
        self.generate_content = AsyncMock(side_effect=client._generate)


class _FakeClient:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error
        self.calls: list[str] = []
        models = _FakeModels(self)
        self.aio = type("Aio", (), {"models": models})()
        # keep a direct handle for assertions
        self.generate_content = models.generate_content

    async def _generate(self, model, contents, config=None):
        self.calls.append(model)
        if self.error:
            raise self.error
        return self.result


class TestKnowledgeExtractor:
    def _resp(self, payload: dict):
        return type("R", (), {"parsed": payload, "text": None})()

    async def test_extract_empty_content_no_api(self) -> None:
        client = _FakeClient(result=self._resp({}))
        assert await KnowledgeExtractor(client=client).extract("   ") == _empty()
        assert client.calls == []

    async def test_extract_happy(self) -> None:
        payload = {
            "entities": [{"name": "Asep", "category": "Person"}],
            "relationships": [],
            "facts": ["Asep is here"],
            "confidence": 0.9,
        }
        client = _FakeClient(result=self._resp(payload))
        out = await KnowledgeExtractor(client=client).extract("Asep is here")
        assert out == _normalize(payload)
        assert client.calls == ["gemini-2.5-flash"]  # text model from settings

    async def test_extract_api_failure_returns_empty(self) -> None:
        client = _FakeClient(error=RuntimeError("api down"))
        out = await KnowledgeExtractor(client=client).extract("Asep is here")
        assert out == _empty()
