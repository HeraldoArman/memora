"""Persons endpoint — Neo4j Person nodes + face capture counts from Postgres."""

from __future__ import annotations

from fastapi import APIRouter, Request
from graph import repository as graph_repo
from sqlalchemy import func, select

from postgres.models import FaceEmbedding
from postgres.session import get_sessionmaker

router = APIRouter()


@router.get("/persons")
async def list_persons(request: Request) -> list[dict]:
    """List all Person nodes from Neo4j, enriched with face capture counts from
    Postgres (FaceEmbedding rows per person_id)."""
    kg = graph_repo.KnowledgeGraphRepo()
    person_repo = graph_repo.PersonRepo()

    # Search all Person nodes — empty query matches everything (CONTAINS "" is true).
    persons = await kg.search_entity("", limit=100)
    persons = [p for p in persons if p.get("label") == "Person"]

    # Count face captures per person_id from Postgres
    capture_counts: dict[str, int] = {}
    sm = get_sessionmaker()
    async with sm() as db:
        result = await db.execute(
            select(FaceEmbedding.person_id, func.count(FaceEmbedding.id)).group_by(
                FaceEmbedding.person_id
            )
        )
        capture_counts = {pid: cnt for pid, cnt in result.all()}

    out: list[dict] = []
    for p in persons:
        pid = p.get("person_id")
        profile = await person_repo.get_person(pid) if pid else None
        out.append(
            {
                "person_id": pid,
                "name": p.get("name"),
                "notes": profile.get("notes") if profile else None,
                "capture_count": capture_counts.get(pid, 0) if pid else 0,
            }
        )
    return out
