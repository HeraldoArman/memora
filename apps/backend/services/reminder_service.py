"""Reminder service — wraps ReminderRepo over Postgres."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from postgres.repositories import ReminderRepo
from postgres.session import get_sessionmaker
from utils.time_ids import now_utc


class ReminderService:
    def __init__(self, repo: ReminderRepo | None = None) -> None:
        self.repo = repo or ReminderRepo()

    async def create(self, *, title: str, due_at: datetime, note: str | None = None) -> dict:
        sm = get_sessionmaker()
        async with sm() as db:
            r = await self.repo.create(db, title=title, due_at=due_at, note=note)
            return _to_dict(r)

    async def update(
        self,
        reminder_id: UUID,
        *,
        title: str | None = None,
        note: str | None = None,
        due_at: datetime | None = None,
        completed: bool | None = None,
    ) -> dict | None:
        sm = get_sessionmaker()
        async with sm() as db:
            r = await self.repo.update(
                db, reminder_id, title=title, note=note, due_at=due_at, completed=completed
            )
            return _to_dict(r) if r is not None else None

    async def delete(self, reminder_id: UUID) -> bool:
        sm = get_sessionmaker()
        async with sm() as db:
            return await self.repo.delete(db, reminder_id)

    async def search(self, query: str) -> list[dict]:
        sm = get_sessionmaker()
        async with sm() as db:
            rs = await self.repo.search(db, query)
            return [_to_dict(r) for r in rs]

    async def today(self, *, now: datetime | None = None) -> list[dict]:
        sm = get_sessionmaker()
        async with sm() as db:
            n = now or now_utc()
            day_start = n.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            rs = await self.repo.due_today(db, day_start=day_start, day_end=day_end)
            return [_to_dict(r) for r in rs]

    async def upcoming(self, *, after: datetime | None = None, limit: int = 20) -> list[dict]:
        sm = get_sessionmaker()
        async with sm() as db:
            rs = await self.repo.upcoming(db, after=after or now_utc(), limit=limit)
            return [_to_dict(r) for r in rs]


def _to_dict(r) -> dict:
    return {
        "reminder_id": str(r.id),
        "title": r.title,
        "note": r.note,
        "due_at": r.due_at.isoformat() if r.due_at else None,
        "completed": r.completed,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
