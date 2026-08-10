"""Face service — register/lookup faces against the FAISS index.

Thin wrapper around FaceRepository. The index + sidecar are wired at startup (lifespan)
and shared across services. No persistence of the sidecar here — the seed script + lifespan
handle loading/saving the index; the person_id↔row map is rebuilt from a sidecar file.
"""

from __future__ import annotations

from vector import repository as vector_repo


class FaceService:
    def __init__(self, face_repo: vector_repo.FaceRepository) -> None:
        self.face_repo = face_repo

    def register(self, embedding, person_id: str) -> int:
        """Add a face vector. Returns the FAISS row id."""
        return self.face_repo.register(embedding, person_id)

    def lookup(self, embedding) -> dict:
        """Identify a face → {person_id, known, possible, score}."""
        hit = self.face_repo.lookup(embedding)
        return {
            "person_id": hit.person_id,
            "known": hit.is_known,
            "possible": hit.is_possible,
            "score": hit.score,
        }

    @property
    def size(self) -> int:
        return self.face_repo.size
