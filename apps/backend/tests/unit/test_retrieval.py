"""Unit tests — retrieval with text embeddings: semantic search + fallback.

Verifies the retriever uses text embeddings when available, falls back to name-substring
when not, and merges results from both paths.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import numpy as np

from memory.retrieval.retriever import Retriever, _dedup, _from_entity


class TestRetrieverWithEmbeddings:
    async def test_uses_text_index_when_available(self) -> None:
        embedder = AsyncMock()
        embedder.embed = AsyncMock(return_value=np.ones(4, dtype=np.float32))
        index = MagicMock()
        index.size = 2
        index.search = MagicMock(return_value=[("Asep likes sushi", 0.95)])
        retriever = Retriever(
            knowledge_service=AsyncMock(),
            memory_service=AsyncMock(),
            text_embedder=embedder,
            text_index=index,
        )
        retriever.knowledge_service.search_entity = AsyncMock(return_value=[])
        retriever.memory_service.recent_memories = AsyncMock(return_value=[])
        results = await retriever.retrieve("sushi")
        assert any(c["source"] == "faiss_text" for c in results), results
        assert any(c["content"] == "Asep likes sushi" for c in results), results

    async def test_falls_back_without_embedder(self) -> None:
        retriever = Retriever(
            knowledge_service=AsyncMock(),
            memory_service=AsyncMock(),
        )
        retriever.knowledge_service.search_entity = AsyncMock(
            return_value=[{"name": "Asep", "label": "Person", "person_id": "pid1"}]
        )
        retriever.memory_service.recent_memories = AsyncMock(return_value=[])
        results = await retriever.retrieve("Asep")
        assert any(c["content"] == "Asep" for c in results), results
        # no faiss_text source
        assert not any(c["source"] == "faiss_text" for c in results), results

    async def test_empty_text_index_falls_back(self) -> None:
        embedder = AsyncMock()
        embedder.embed = AsyncMock(return_value=np.ones(4, dtype=np.float32))
        index = MagicMock()
        index.size = 0  # empty index
        retriever = Retriever(
            knowledge_service=AsyncMock(),
            memory_service=AsyncMock(),
            text_embedder=embedder,
            text_index=index,
        )
        retriever.knowledge_service.search_entity = AsyncMock(
            return_value=[{"name": "Asep", "label": "Person", "person_id": "pid1"}]
        )
        retriever.memory_service.recent_memories = AsyncMock(return_value=[])
        results = await retriever.retrieve("Asep")
        # graph results still present
        assert any(c["content"] == "Asep" for c in results), results
        # no faiss_text results (index was empty)
        assert not any(c["source"] == "faiss_text" for c in results), results
        # search not called on empty index
        index.search.assert_not_called()

    async def test_embed_failure_graceful(self) -> None:
        embedder = AsyncMock()
        embedder.embed = AsyncMock(side_effect=RuntimeError("api down"))
        index = MagicMock()
        index.size = 2
        retriever = Retriever(
            knowledge_service=AsyncMock(),
            memory_service=AsyncMock(),
            text_embedder=embedder,
            text_index=index,
        )
        retriever.knowledge_service.search_entity = AsyncMock(return_value=[])
        retriever.memory_service.recent_memories = AsyncMock(return_value=[])
        results = await retriever.retrieve("sushi")
        # no crash, just no text results
        assert not any(c["source"] == "faiss_text" for c in results), results


class TestConsolidatorWithEmbeddings:
    async def test_facts_embedded_when_wired(self) -> None:
        from pipeline.consolidator import Consolidator

        embedder = AsyncMock()
        embedder.embed_batch = AsyncMock(
            return_value=[np.ones(768, dtype=np.float32), np.ones(768, dtype=np.float32)]
        )
        index = MagicMock()
        index.add = MagicMock(return_value=0)
        c = Consolidator(
            person_service=AsyncMock(),
            knowledge_service=AsyncMock(),
            memory_service=AsyncMock(),
            text_embedder=embedder,
            text_index=index,
        )
        c.person_service.register_person = AsyncMock(return_value={"person_id": "p1"})
        c.knowledge_service.upsert_entity = AsyncMock(return_value={})
        c.knowledge_service.add_relation = AsyncMock(return_value={})
        c.memory_service.add_message = AsyncMock(return_value=None)
        c.memory_service.add_facts = AsyncMock(return_value=2)
        extraction = {
            "confidence": 0.95,
            "entities": [{"name": "Asep", "category": "Person"}],
            "relationships": [],
            "facts": ["Asep likes sushi", "Asep works at Tokopedia"],
        }
        await c.consolidate(extraction, content="I'm Asep")
        embedder.embed_batch.assert_awaited_once()
        assert index.add.call_count == 2

    async def test_facts_not_embedded_when_not_wired(self) -> None:
        from unittest.mock import AsyncMock

        from pipeline.consolidator import Consolidator

        c = Consolidator(
            person_service=AsyncMock(),
            knowledge_service=AsyncMock(),
            memory_service=AsyncMock(),
        )
        c.person_service.register_person = AsyncMock(return_value={"person_id": "p1"})
        c.knowledge_service.upsert_entity = AsyncMock(return_value={})
        c.knowledge_service.add_relation = AsyncMock(return_value={})
        c.memory_service.add_message = AsyncMock(return_value=None)
        c.memory_service.add_facts = AsyncMock(return_value=1)
        await c.consolidate(
            {
                "confidence": 0.95,
                "entities": [{"name": "Asep", "category": "Person"}],
                "facts": ["Asep is here"],
            },
            content="Asep",
        )
        # no embedder → no embed_batch call (it's None)
        assert c.text_embedder is None


class TestDedup:
    def test_dedup_by_source_id_content(self) -> None:
        candidates = [
            {"source": "neo4j", "source_id": "1", "content": "Asep"},
            {"source": "neo4j", "source_id": "1", "content": "Asep"},  # dup
            {"source": "postgres", "source_id": "s1", "content": "Asep"},
        ]
        out = _dedup(candidates)
        assert len(out) == 2


class TestFromEntity:
    def test_shape(self) -> None:
        d = _from_entity({"name": "Asep", "label": "Person", "person_id": "p1"})
        assert d["content"] == "Asep"
        assert d["category"] == "Person"
        assert d["source"] == "neo4j"
        assert d["source_id"] == "p1"
