"""Reminder repository."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from postgres.models import Reminder


class ReminderRepo:
    """CRUD for reminders."""

    async def create(
        self, db: AsyncSession, *, title: str, due_at: datetime, note: str | None = None
    ) -> Reminder:
        r = Reminder(title=title, due_at=due_at, note=note)
        db.add(r)
        await db.commit()
        await db.refresh(r)
        return r

    async def get(self, db: AsyncSession, reminder_id: UUID) -> Reminder | None:
        return await db.get(Reminder, reminder_id)

    async def update(
        self,
        db: AsyncSession,
        reminder_id: UUID,
        *,
        title: str | None = None,
        note: str | None = None,
        due_at: datetime | None = None,
        completed: bool | None = None,
    ) -> Reminder | None:
        r = await db.get(Reminder, reminder_id)
        if r is None:
            return None
        if title is not None:
            r.title = title
        if note is not None:
            r.note = note
        if due_at is not None:
            r.due_at = due_at
        if completed is not None:
            r.completed = completed
        await db.commit()
        await db.refresh(r)
        return r

    async def delete(self, db: AsyncSession, reminder_id: UUID) -> bool:
        r = await db.get(Reminder, reminder_id)
        if r is None:
            return False
        await db.delete(r)
        await db.commit()
        return True

    async def search(self, db: AsyncSession, query: str, *, limit: int = 20) -> list[Reminder]:
        result = await db.execute(
            select(Reminder)
            .where(Reminder.title.ilike(f"%{query}%") | Reminder.note.ilike(f"%{query}%"))
            .order_by(Reminder.due_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def due_today(
        self, db: AsyncSession, *, day_start: datetime, day_end: datetime
    ) -> list[Reminder]:
        result = await db.execute(
            select(Reminder)
            .where(Reminder.due_at >= day_start, Reminder.due_at < day_end, ~Reminder.completed)
            .order_by(Reminder.due_at)
        )
        return list(result.scalars().all())

    async def upcoming(
        self, db: AsyncSession, *, after: datetime, limit: int = 20
    ) -> list[Reminder]:
        result = await db.execute(
            select(Reminder)
            .where(Reminder.due_at >= after, ~Reminder.completed)
            .order_by(Reminder.due_at)
            .limit(limit)
        )
        return list(result.scalars().all())
