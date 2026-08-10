"""FAISS face index — IndexFlatIP over 512-d normalized vectors.

Inner product over L2-normalized vectors == cosine similarity in [-1, 1].
FAISS stores vectors only; the person_id<->row mapping lives in a sidecar list
held by FaceRepository (Phase 2). Here we keep the index primitive.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

import faiss


class FaceIndex:
    """Thin wrapper around faiss.IndexFlatIP for normalized face embeddings."""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim
        self._index = faiss.IndexFlatIP(dim)

    @property
    def size(self) -> int:
        return self._index.ntotal

    def add(self, vectors: np.ndarray) -> None:
        """Add one or many (n, dim) normalized vectors."""
        vecs = np.ascontiguousarray(vectors, dtype=np.float32)
        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)
        if vecs.shape[1] != self.dim:
            raise ValueError(f"vector dim {vecs.shape[1]} != index dim {self.dim}")
        self._index.add(vecs)

    def search(self, query: np.ndarray, k: int = 1) -> tuple[np.ndarray, np.ndarray]:
        """Return (scores, row_ids) of top-k matches. Row ids index into the sidecar map."""
        q = np.ascontiguousarray(query, dtype=np.float32).reshape(1, -1)
        scores, ids = self._index.search(q, k)
        return scores[0], ids[0]

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(path))

    @classmethod
    def load(cls, path: str | Path, dim: int = 512) -> FaceIndex:
        idx = cls(dim=dim)
        if Path(path).exists():
            idx._index = faiss.read_index(str(path))
        return idx
