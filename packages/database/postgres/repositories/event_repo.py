"""Calendar event repository."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from postgres.models import Event


class EventRepo:
    """CRUD for calendar events."""

    async def create(
        self,
        db: AsyncSession,
        *,
        title: str,
        starts_at: datetime,
        description: str | None = None,
        location: str | None = None,
        ends_at: datetime | None = None,
    ) -> Event:
        ev = Event(
            title=title,
            starts_at=starts_at,
            description=description,
            location=location,
            ends_at=ends_at,
        )
        db.add(ev)
        await db.commit()
        await db.refresh(ev)
        return ev

    async def get(self, db: AsyncSession, event_id: UUID) -> Event | None:
        return await db.get(Event, event_id)

    async def upcoming(self, db: AsyncSession, *, after: datetime, limit: int = 20) -> list[Event]:
        result = await db.execute(
            select(Event).where(Event.starts_at >= after).order_by(Event.starts_at).limit(limit)
        )
        return list(result.scalars().all())

    async def search(self, db: AsyncSession, query: str, *, limit: int = 20) -> list[Event]:
        result = await db.execute(
            select(Event)
            .where(Event.title.ilike(f"%{query}%"))
            .order_by(Event.starts_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete(self, db: AsyncSession, event_id: UUID) -> None:
        ev = await db.get(Event, event_id)
        if ev is not None:
            await db.delete(ev)
            await db.commit()
