"""Person service — bridges Neo4j (profile + relations) and FAISS (face identity).

Tool → service → repo. Owns the Postgres session lifecycle for any relational side effects;
graph + vector calls go through their own clients. Single implicit device → no user scoping.
"""

from __future__ import annotations

from graph import repository as graph_repo
from vector import repository as vector_repo


class PersonService:
    """Register, look up, and enrich people across the graph + face index."""

    def __init__(
        self,
        person_repo: graph_repo.PersonRepo | None = None,
        kg_repo: graph_repo.KnowledgeGraphRepo | None = None,
        face_repo: vector_repo.FaceRepository | None = None,
    ) -> None:
        self.person_repo = person_repo or graph_repo.PersonRepo()
        self.kg_repo = kg_repo or graph_repo.KnowledgeGraphRepo()
        self.face_repo = face_repo

    async def register_person(self, *, name: str, person_id: str | None = None) -> dict:
        """Create or update a Person node. Returns the node dict."""
        from utils.time_ids import gen_id

        pid = person_id or gen_id()
        return await self.person_repo.upsert_person(person_id=pid, name=name)

    async def update_person(self, *, person_id: str, notes: str | None = None) -> dict | None:
        person = await self.person_repo.get_person(person_id)
        if person is None:
            return None
        return await self.person_repo.upsert_person(
            person_id=person_id, name=person["name"], notes=notes
        )

    async def get_person(self, person_id: str) -> dict | None:
        return await self.person_repo.get_person(person_id)

    async def search_by_name(self, name: str) -> list[dict]:
        """Search any entity by name; callers filter Person nodes if needed."""
        return await self.kg_repo.search_entity(name)

    async def search_by_face(self, embedding) -> dict:
        """Identify a visible person via the FAISS index. No face_repo → unknown."""
        if self.face_repo is None:
            return {"person_id": None, "known": False, "possible": False, "score": 0.0}
        lookup = self.face_repo.lookup(embedding)
        person: dict = {"person_id": None, "known": False, "possible": False, "score": lookup.score}
        if lookup.person_id is not None:
            person["person_id"] = lookup.person_id
            person["known"] = lookup.is_known
            person["possible"] = lookup.is_possible
            profile = await self.person_repo.get_person(lookup.person_id)
            if profile is not None:
                person["name"] = profile.get("name")
        return person

    async def related_people(self, person_id: str) -> list[dict]:
        return await self.person_repo.related_people(person_id)

    async def register_face(self, embedding, person_id: str) -> int:
        """Link a face vector to an existing person. Requires face_repo.

        Persistence is the caller's responsibility (the runtime tool path saves the index
        after a successful enroll) — keeping it out of the service keeps this method a
        pure FAISS mutation that's testable without a writable index path.
        """
        if self.face_repo is None:
            raise RuntimeError("FaceRepository not configured — wire it at startup.")
        return self.face_repo.register(embedding, person_id)
