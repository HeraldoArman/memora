"""Memories endpoint — extracted facts from Postgres (episodic + semantic)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from postgres.repositories import FactRepo
from postgres.session import get_sessionmaker

router = APIRouter()

_repo = FactRepo()


@router.get("/memories")
async def list_memories(
    limit: int = Query(50, ge=1, le=200),
    person_id: str | None = Query(None),
) -> list[dict]:
    """Recent extracted memory facts, optionally filtered by person."""
    sm = get_sessionmaker()
    async with sm() as db:
        facts = await _repo.list_recent(db, limit=limit, person_id=person_id)
        return [
            {
                "id": str(f.id),
                "fact": f.fact,
                "category": f.category,
                "confidence": f.confidence,
                "person_id": f.person_id,
                "session_id": str(f.session_id) if f.session_id else None,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in facts
        ]
