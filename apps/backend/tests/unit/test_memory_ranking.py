"""Unit tests — memory: ranker scoring + retriever candidate shape/dedup.

Ranker is pure (deterministic tokens/decay). Retriever uses AsyncMock services.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from memory.ranking.ranker import rank, semantic_similarity, temporal_score
from memory.retrieval.retriever import Retriever

NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)


class TestSemanticSimilarity:
    def test_overlap(self) -> None:
        assert semantic_similarity("Asep Tokopedia", "Asep works at Tokopedia") > 0
        assert semantic_similarity("kopi", "sushi") == 0.0

    def test_empty(self) -> None:
        assert semantic_similarity("", "content") == 0.0
        assert semantic_similarity("query", "") == 0.0

    def test_short_tokens_filtered(self) -> None:
        # 1-char tokens dropped from both sides
        assert semantic_similarity("a b c", "a b c d") == 0.0


class TestTemporalScore:
    def test_never_ago_is_one(self) -> None:
        assert temporal_score(NOW, now=NOW) == 1.0

    def test_decays(self) -> None:
        day = datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC)
        assert 0.0 < temporal_score(day, now=NOW) < 1.0

    def test_half_life(self) -> None:
        # 14 days ago → ~0.5
        old = datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)
        assert temporal_score(old, now=NOW) == 0.5 ** (14.0 / 14.0)

    def test_naive_datetime_assumed_utc(self) -> None:
        naive = datetime(2026, 8, 10, 12, 0, 0)  # no tz
        assert temporal_score(naive, now=NOW) == 1.0

    def test_none(self) -> None:
        assert temporal_score(None) == 0.0


class TestRank:
    def _candidates(self) -> list[dict]:
        return [
            {
                "content": "Asep works at Tokopedia",
                "created_at": "2026-08-09T12:00:00+00:00",
                "related_people": ["Asep"],
                "confidence": 0.9,
                "frequency": 3,
            },
            {
                "content": "Budi likes sushi",
                "created_at": "2026-07-01T12:00:00+00:00",
                "related_people": ["Budi"],
                "confidence": 0.8,
                "frequency": 1,
            },
            {
                "content": "Asep lives in Jakarta",
                "created_at": "2026-08-08T12:00:00+00:00",
                "related_people": ["Asep"],
                "location": "Jakarta",
                "confidence": 0.7,
            },
        ]

    def test_top_semantic_and_social(self) -> None:
        ranked = rank(self._candidates(), query="Asep Tokopedia", visible_people=["Asep"], now=NOW)
        top = ranked[0]
        assert "Tokopedia" in top[0]["content"]
        assert top[2]["semantic"] > 0 and top[2]["social"] == 1.0

    def test_sorted_desc(self) -> None:
        ranked = rank([], query="x")
        scores = [r[1] for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_spatial_match(self) -> None:
        ranked = rank(self._candidates(), query="", location="Jakarta", now=NOW)
        jakarta = next(r for r in ranked if "Jakarta" in r[0]["content"])
        assert jakarta[2]["spatial"] == 1.0

    def test_recency_beats_frequency_when_equal_weight(self) -> None:
        # candidate A is 1 day old, candidate B is 40 days old; both no visible-person/semantic
        candidates = [
            {
                "content": "AAA xyz",
                "created_at": "2026-08-09T12:00:00+00:00",
                "confidence": 0.5,
                "frequency": 1,
            },
            {
                "content": "BBB xyz",
                "created_at": "2026-07-01T12:00:00+00:00",
                "confidence": 0.5,
                "frequency": 1,
            },
        ]
        ranked = rank(candidates, query="", now=NOW)
        assert ranked[0][0]["content"] == "AAA xyz"
        assert ranked[0][2]["temporal"] > ranked[1][2]["temporal"]

    def test_frequency_saturates(self) -> None:
        ranked = rank([{"content": "x", "frequency": 99}], query="", now=NOW)
        assert ranked[0][2]["frequency"] == 1.0

    def test_missing_fields_neutral(self) -> None:
        ranked = rank([{"content": "solo"}], query="", now=NOW)
        c, score, signals = ranked[0]
        assert score >= 0.0 and signals["temporal"] == 0.0


class TestRetriever:
    def _retriever(self) -> Retriever:
        r = Retriever(
            person_service=AsyncMock(),
            knowledge_service=AsyncMock(),
            memory_service=AsyncMock(),
        )
        r.knowledge_service.search_entity = AsyncMock(
            return_value=[{"name": "Asep", "label": "Person", "person_id": "pid1"}]
        )
        r.memory_service.recent_memories = AsyncMock(
            return_value=[
                {"session_id": "s1", "summary": "met Asep", "started_at": None},
                {"session_id": "s2", "summary": None, "started_at": None},
            ]
        )
        return r

    async def test_retrieve_shape_and_dedup(self) -> None:
        r = self._retriever()
        out = await r.retrieve("Asep", visible_people=["Asep"])
        # Asep appears via visible-person search + query search → dedup keeps one
        asep = [c for c in out if c["content"] == "Asep"]
        assert len(asep) == 1
        assert asep[0]["source"] == "neo4j"
        assert asep[0]["source_id"] == "pid1"
        # episodic candidates normalized with category Episodic
        epi = [c for c in out if c["category"] == "Episodic"]
        assert len(epi) == 2
        # empty summary falls back to session_id
        assert any(c["content"] == "s2" for c in epi)

    async def test_retrieve_no_query_no_visible(self) -> None:
        r = self._retriever()
        out = await r.retrieve("")
        # empty query + no visible people → graph search skipped entirely
        r.knowledge_service.search_entity.assert_not_awaited()
        r.memory_service.recent_memories.assert_awaited_once()
        assert len(out) >= 2  # recent episodic still returned

    async def test_retrieve_empty_result(self) -> None:
        r = self._retriever()
        r.knowledge_service.search_entity = AsyncMock(return_value=[])
        r.memory_service.recent_memories = AsyncMock(return_value=[])
        assert await r.retrieve("nothing") == []

    async def test_retrieve_degrades_on_service_failure(self) -> None:
        # retrieve() has no try/except — degradation is ContextEngine.build's job.
        r = self._retriever()
        r.knowledge_service.search_entity = AsyncMock(side_effect=RuntimeError("neo4j down"))
        with pytest.raises(RuntimeError, match="neo4j down"):
            await r.retrieve("Asep", visible_people=["Asep"])
