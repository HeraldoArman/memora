"""Retriever — query Neo4j (semantic) + Postgres (episodic) + FAISS (face) for context.

context.md §8 (retrieval). Wraps the service layer (which already wraps the repos) —
no separate graph_store/episodic_store wrapper classes; services are the store seam.

Returns a flat list of candidate dicts with a normalized shape the ranker consumes:
  {content, category, created_at, confidence, related_people, location, source, source_id}

Ponytail: for the hackathon, retrieval = name-substring graph search + recent episodic
sessions + (optional) face lookup. No vector embedding of the query yet — that would need a
text-embedding model call per query. Token-overlap ranking covers the "Asep?" case well.
"""

from __future__ import annotations

import logging

from services import KnowledgeService, MemoryService, PersonService

logger = logging.getLogger(__name__)


class Retriever:
    """Fetch memory candidates from the graph + episodic store."""

    def __init__(
        self,
        *,
        person_service: PersonService | None = None,
        knowledge_service: KnowledgeService | None = None,
        memory_service: MemoryService | None = None,
    ) -> None:
        self.person_service = person_service or PersonService()
        self.knowledge_service = knowledge_service or KnowledgeService()
        self.memory_service = memory_service or MemoryService()

    async def retrieve(
        self,
        query: str,
        *,
        visible_people: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Return candidate memories for `query` + currently visible people."""
        candidates: list[dict] = []
        # 1. Graph: search entities by name substring + each visible person's profile.
        for name in visible_people or []:
            hits = await self.knowledge_service.search_entity(name)
            for h in hits:
                candidates.append(_from_entity(h))
        if query:
            ents = await self.knowledge_service.search_entity(query)
            for e in ents:
                candidates.append(_from_entity(e))
        # 2. Episodic: recent conversation sessions (titles/summaries as lightweight memories).
        recent = await self.memory_service.recent_memories(limit=limit)
        for r in recent:
            candidates.append(
                {
                    "content": r.get("summary") or r.get("session_id", ""),
                    "category": "Episodic",
                    "created_at": r.get("started_at"),
                    "source": "postgres",
                    "source_id": r.get("session_id"),
                }
            )
        return _dedup(candidates)


def _from_entity(h: dict) -> dict:
    return {
        "content": h.get("name", ""),
        "category": h.get("label"),
        "source": "neo4j",
        "source_id": h.get("person_id"),
    }


def _dedup(candidates: list[dict]) -> list[dict]:
    """Dedup by (source, source_id, content) — graph + episodic can overlap on a name."""
    seen: set[tuple] = set()
    out: list[dict] = []
    for c in candidates:
        key = (c.get("source"), c.get("source_id"), c.get("content"))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


# --- self-check: shape + dedup with stubbed services ---
def _self_check() -> None:  # pragma: no cover
    import asyncio
    from unittest.mock import AsyncMock

    r = Retriever(
        person_service=AsyncMock(spec=PersonService),
        knowledge_service=AsyncMock(spec=KnowledgeService),
        memory_service=AsyncMock(spec=MemoryService),
    )
    r.knowledge_service.search_entity = AsyncMock(
        return_value=[{"name": "Asep", "label": "Person", "person_id": "pid1"}]
    )
    r.memory_service.recent_memories = AsyncMock(
        return_value=[{"session_id": "s1", "summary": "met Asep", "started_at": None}]
    )
    out = asyncio.run(r.retrieve("Asep", visible_people=["Asep"]))
    # Asep appears via visible-people search + query search → dedup keeps one
    asep_hits = [c for c in out if c["content"] == "Asep"]
    assert len(asep_hits) == 1, asep_hits
    assert any(c["content"] == "met Asep" for c in out), out
    print(f"retriever self-check OK: {len(out)} candidates")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
