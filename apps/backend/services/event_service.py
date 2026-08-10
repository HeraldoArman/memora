"""Event service — calendar events over Postgres."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from postgres.repositories import EventRepo
from postgres.session import get_sessionmaker


class EventService:
    def __init__(self, repo: EventRepo | None = None) -> None:
        self.repo = repo or EventRepo()

    async def create(
        self,
        *,
        title: str,
        starts_at: datetime,
        description: str | None = None,
        location: str | None = None,
        ends_at: datetime | None = None,
    ) -> dict:
        sm = get_sessionmaker()
        async with sm() as db:
            ev = await self.repo.create(
                db,
                title=title,
                starts_at=starts_at,
                description=description,
                location=location,
                ends_at=ends_at,
            )
            return _to_dict(ev)

    async def upcoming(self, *, after: datetime | None = None, limit: int = 20) -> list[dict]:
        sm = get_sessionmaker()
        async with sm() as db:
            from utils.time_ids import now_utc

            evs = await self.repo.upcoming(db, after=after or now_utc(), limit=limit)
            return [_to_dict(e) for e in evs]

    async def search(self, query: str) -> list[dict]:
        sm = get_sessionmaker()
        async with sm() as db:
            evs = await self.repo.search(db, query)
            return [_to_dict(e) for e in evs]

    async def delete(self, event_id: UUID) -> None:
        sm = get_sessionmaker()
        async with sm() as db:
            await self.repo.delete(db, event_id)


def _to_dict(e) -> dict:
    return {
        "event_id": str(e.id),
        "title": e.title,
        "description": e.description,
        "location": e.location,
        "starts_at": e.starts_at.isoformat() if e.starts_at else None,
        "ends_at": e.ends_at.isoformat() if e.ends_at else None,
    }
