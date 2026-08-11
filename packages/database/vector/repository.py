"""FaceRepository — ties the FAISS index to a person_id sidecar.

FAISS stores vectors only (no metadata). We keep a parallel list `person_ids` where
index i ↔ person_ids[i]. register() appends; lookup() searches and maps row→person_id.
The sidecar lives in memory; the durable store is the face_embeddings Postgres table.
Both the backend and worker rebuild their in-process FAISS index from Postgres on startup.

face_recognition.md §10 thresholds: >=0.50 known, 0.35–0.50 possible, <0.35 unknown.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from vector.embeddings import l2_normalize
from vector.index import FaceIndex


class FaceLookup:
    """Result of FaceRepository.lookup()."""

    def __init__(
        self, person_id: str | None, score: float, is_known: bool, is_possible: bool
    ) -> None:
        self.person_id = person_id
        self.score = score
        self.is_known = is_known
        self.is_possible = is_possible

    def __repr__(self) -> str:
        return f"FaceLookup(person_id={self.person_id!r}, score={self.score:.3f}, known={self.is_known})"


class FaceRepository:
    """Index + person_id sidecar for face identity."""

    def __init__(
        self,
        index: FaceIndex,
        person_ids: list[str] | None = None,
        *,
        known_threshold: float = 0.50,
        possible_threshold: float = 0.35,
    ) -> None:
        self.index = index
        self.person_ids: list[str] = person_ids if person_ids is not None else []
        self.known_threshold = known_threshold
        self.possible_threshold = possible_threshold

    @property
    def size(self) -> int:
        return self.index.size

    def register(self, embedding: np.ndarray, person_id: str) -> int:
        """Add a face vector for person_id. Returns the FAISS row id."""
        vec = l2_normalize(embedding).astype(np.float32)
        self.index.add(vec)
        row = self.index.size - 1
        self.person_ids.append(person_id)
        return row

    def lookup(self, embedding: np.ndarray) -> FaceLookup:
        """Search for the nearest registered face. Empty index → unknown."""
        if self.index.size == 0:
            return FaceLookup(None, 0.0, is_known=False, is_possible=False)
        vec = l2_normalize(embedding).astype(np.float32)
        scores, ids = self.index.search(vec, k=1)
        score = float(scores[0])
        row = int(ids[0])
        if row < 0 or row >= len(self.person_ids):
            return FaceLookup(None, score, is_known=False, is_possible=False)
        person_id = self.person_ids[row]
        is_known = score >= self.known_threshold
        is_possible = (not is_known) and score >= self.possible_threshold
        if not is_known and not is_possible:
            return FaceLookup(None, score, is_known=False, is_possible=False)
        return FaceLookup(person_id, score, is_known=is_known, is_possible=is_possible)

    def save(self, path: str) -> None:
        """Persist the FAISS index + person_id sidecar (JSON next to the index file)."""
        self.index.save(path)
        sidecar = Path(str(path) + ".sidecar.json")
        sidecar.write_text(json.dumps(self.person_ids))

    @classmethod
    def load(
        cls, path: str, *, known_threshold: float = 0.50, possible_threshold: float = 0.35
    ) -> FaceRepository:
        """Load index + sidecar. Missing sidecar → empty (fresh) mapping."""
        from vector.index import FaceIndex

        index = FaceIndex.load(path)
        sidecar = Path(str(path) + ".sidecar.json")
        person_ids = json.loads(sidecar.read_text()) if sidecar.exists() else []
        return cls(
            index,
            person_ids,
            known_threshold=known_threshold,
            possible_threshold=possible_threshold,
        )

    @classmethod
    async def from_db(
        cls,
        *,
        known_threshold: float = 0.50,
        possible_threshold: float = 0.35,
        dim: int = 512,
    ) -> FaceRepository:
        """Rebuild the in-process FAISS index from the face_embeddings Postgres table.

        This is the durable path on Railway: both backend and worker call this on startup
        instead of relying on a shared volume for the .faiss file.
        """
        from postgres.repositories import FaceEmbeddingRepo
        from postgres.session import get_sessionmaker

        repo = FaceEmbeddingRepo()
        index = FaceIndex(dim=dim)
        person_ids: list[str] = []
        sm = get_sessionmaker()
        async with sm() as db:
            rows = await repo.load_all(db)
        import logging as _log

        _log.getLogger(__name__).info(
            "from_db: loaded %d face embedding(s) from Postgres", len(rows)
        )
        for person_id, emb in rows:
            index.add(l2_normalize(emb).astype(np.float32))
            person_ids.append(person_id)
        return cls(
            index,
            person_ids,
            known_threshold=known_threshold,
            possible_threshold=possible_threshold,
        )
