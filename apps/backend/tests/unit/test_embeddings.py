"""Unit tests — text embeddings: TextEmbedder parse + normalize + failure paths,
TextMemoryIndex add/search/save/load.

No live API: genai.Client is mocked. FAISS runs in-process (faiss-cpu).
"""

from __future__ import annotations

import tempfile
from unittest.mock import AsyncMock

import numpy as np
import pytest
from vector.text_index import TextMemoryIndex

from perception.embeddings.text_embeddings import TextEmbedder, _extract_embeddings, _l2_normalize


class TestL2Normalize:
    def test_unit_norm(self) -> None:
        v = np.array([3.0, 4.0], dtype=np.float32)
        n = _l2_normalize(v)
        assert abs(np.linalg.norm(n) - 1.0) < 1e-6

    def test_zero_vector(self) -> None:
        v = np.zeros(3, dtype=np.float32)
        n = _l2_normalize(v)
        assert np.allclose(n, 0.0)


class TestExtractEmbeddings:
    def test_normal(self) -> None:
        emb = type("E", (), {"values": [1.0, 2.0, 3.0]})()
        resp = type("R", (), {"embeddings": [emb]})()
        vecs = _extract_embeddings(resp)
        assert len(vecs) == 1
        assert vecs[0].shape == (3,)

    def test_empty(self) -> None:
        resp = type("R", (), {"embeddings": None})()
        assert _extract_embeddings(resp) == []

    def test_none_values(self) -> None:
        emb = type("E", (), {"values": None})()
        resp = type("R", (), {"embeddings": [emb]})()
        vecs = _extract_embeddings(resp)
        assert vecs == [None]


class TestTextEmbedder:
    async def test_empty_text(self) -> None:
        emb = TextEmbedder(client=object())
        assert await emb.embed("") is None
        assert await emb.embed("   ") is None

    async def test_api_failure(self) -> None:
        client = AsyncMock()
        client.aio.models.embed_content = AsyncMock(side_effect=RuntimeError("api down"))
        emb = TextEmbedder(client=client)
        assert await emb.embed("hello") is None

    async def test_happy_path(self) -> None:
        emb_obj = type("E", (), {"values": [1.0, 0.0, 0.0, 0.0]})()
        resp = type("R", (), {"embeddings": [emb_obj]})()
        client = AsyncMock()
        client.aio.models.embed_content = AsyncMock(return_value=resp)
        emb = TextEmbedder(client=client)
        vec = await emb.embed("hello")
        assert vec is not None
        assert vec.shape == (4,)
        assert abs(np.linalg.norm(vec) - 1.0) < 1e-6  # L2-normalized

    async def test_batch_empty(self) -> None:
        emb = TextEmbedder(client=object())
        assert await emb.embed_batch([]) == []

    async def test_batch_happy(self) -> None:
        e1 = type("E", (), {"values": [1.0, 0.0]})()
        e2 = type("E", (), {"values": [0.0, 1.0]})()
        resp = type("R", (), {"embeddings": [e1, e2]})()
        client = AsyncMock()
        client.aio.models.embed_content = AsyncMock(return_value=resp)
        emb = TextEmbedder(client=client)
        vecs = await emb.embed_batch(["hello", "world"])
        assert len(vecs) == 2
        assert vecs[0] is not None and vecs[1] is not None
        assert abs(np.linalg.norm(vecs[0]) - 1.0) < 1e-6


class TestTextMemoryIndex:
    def test_empty_search(self) -> None:
        idx = TextMemoryIndex(dim=4)
        assert idx.size == 0
        assert idx.search(np.zeros(4, dtype=np.float32)) == []

    def test_add_and_search(self) -> None:
        idx = TextMemoryIndex(dim=4)
        idx.add(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), "fact1")
        idx.add(np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32), "fact2")
        assert idx.size == 2
        hits = idx.search(np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32), k=2)
        assert hits[0][0] == "fact1"
        assert hits[0][1] > hits[1][1]

    def test_search_k_larger_than_size(self) -> None:
        idx = TextMemoryIndex(dim=4)
        idx.add(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), "fact1")
        hits = idx.search(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), k=10)
        assert len(hits) == 1

    def test_dim_mismatch(self) -> None:
        idx = TextMemoryIndex(dim=4)
        with pytest.raises(ValueError, match="dim"):
            idx.add(np.zeros(3, dtype=np.float32), "bad")

    def test_save_load_roundtrip(self) -> None:
        idx = TextMemoryIndex(dim=4)
        idx.add(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), "fact1")
        idx.add(np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32), "fact2")
        with tempfile.NamedTemporaryFile(suffix=".faiss", delete=False) as f:
            path = f.name
        idx.save(path)
        loaded = TextMemoryIndex.load(path, dim=4)
        assert loaded.size == 2
        assert loaded.memory_ids == ["fact1", "fact2"]
        hits = loaded.search(np.array([0.0, 0.95, 0.0, 0.0], dtype=np.float32), k=1)
        assert hits[0][0] == "fact2"

    def test_load_missing_file(self) -> None:
        loaded = TextMemoryIndex.load("/nonexistent/path.faiss", dim=4)
        assert loaded.size == 0
        assert loaded.memory_ids == []
