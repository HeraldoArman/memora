"""Text memory index — FAISS IndexFlatIP over text embeddings.

Same pattern as FaceIndex/FaceRepository but for memory/fact embeddings. Stores vectors
in FAISS + a sidecar list of memory_id strings. Used by the retriever for semantic search:
query → embed → search → fetch memories by id.

Ponytail: separate index from faces (different dim: 768 vs 512). No Postgres persistence
of embeddings — the FAISS index file is the store, loaded at session start and saved
on each consolidation. If the index is empty/missing, the retriever falls back to
name-substring search.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import faiss


class TextMemoryIndex:
    """FAISS IndexFlatIP + memory_id sidecar for semantic memory search."""

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim
        self._index = faiss.IndexFlatIP(dim)
        self.memory_ids: list[str] = []

    @property
    def size(self) -> int:
        return self._index.ntotal

    def add(self, embedding: np.ndarray, memory_id: str) -> int:
        """Add a text embedding for memory_id. Returns the FAISS row id."""
        vec = np.ascontiguousarray(embedding, dtype=np.float32).reshape(1, -1)
        if vec.shape[1] != self.dim:
            raise ValueError(f"vector dim {vec.shape[1]} != index dim {self.dim}")
        self._index.add(vec)
        row = self._index.ntotal - 1
        self.memory_ids.append(memory_id)
        return row

    def search(self, embedding: np.ndarray, k: int = 10) -> list[tuple[str, float]]:
        """Return [(memory_id, score)] for top-k matches. Empty index → []."""
        if self._index.ntotal == 0:
            return []
        vec = np.ascontiguousarray(embedding, dtype=np.float32).reshape(1, -1)
        scores, ids = self._index.search(vec, min(k, self._index.ntotal))
        out = []
        for score, row in zip(scores[0], ids[0], strict=False):
            if row < 0 or row >= len(self.memory_ids):
                continue
            out.append((self.memory_ids[row], float(score)))
        return out

    def save(self, path: str) -> None:
        """Persist the FAISS index + memory_id sidecar (JSON next to the index file)."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(path))
        sidecar = Path(str(path) + ".sidecar.json")
        sidecar.write_text(json.dumps(self.memory_ids))

    @classmethod
    def load(cls, path: str, dim: int = 768) -> TextMemoryIndex:
        """Load index + sidecar. Missing files → empty (fresh) index."""
        idx = cls(dim=dim)
        if Path(path).exists():
            idx._index = faiss.read_index(str(path))
            sidecar = Path(str(path) + ".sidecar.json")
            if sidecar.exists():
                idx.memory_ids = json.loads(sidecar.read_text())
        return idx


# --- self-check ---
def _self_check() -> None:  # pragma: no cover
    import tempfile

    idx = TextMemoryIndex(dim=4)
    assert idx.size == 0
    assert idx.search(np.zeros(4, dtype=np.float32)) == []

    # add two vectors
    idx.add(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), "fact1")
    idx.add(np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32), "fact2")
    assert idx.size == 2

    # search: query close to fact1
    hits = idx.search(np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32), k=2)
    assert hits[0][0] == "fact1", hits
    assert hits[0][1] > hits[1][1], hits  # cosine similarity ordering

    # save + load roundtrip
    with tempfile.NamedTemporaryFile(suffix=".faiss", delete=False) as f:
        path = f.name
    idx.save(path)
    loaded = TextMemoryIndex.load(path, dim=4)
    assert loaded.size == 2
    assert loaded.memory_ids == ["fact1", "fact2"], loaded.memory_ids
    hits2 = loaded.search(np.array([0.0, 0.95, 0.0, 0.0], dtype=np.float32), k=1)
    assert hits2[0][0] == "fact2", hits2

    print("text memory index self-check OK: add, search, save/load roundtrip")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
