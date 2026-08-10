"""Extracted memory facts repository (raw statement strings)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from postgres.models import MemoryFact


class FactRepo:
    """CRUD for extracted memory facts."""

    async def add_many(
        self,
        db: AsyncSession,
        *,
        facts: list[str],
        session_id: UUID | None = None,
        category: str | None = None,
        confidence: float | None = None,
    ) -> int:
        rows = [
            MemoryFact(
                session_id=session_id,
                fact=f,
                category=category,
                confidence=confidence,
            )
            for f in facts
        ]
        db.add_all(rows)
        await db.commit()
        return len(rows)

    async def list_recent(
        self, db: AsyncSession, *, limit: int = 50, session_id: UUID | None = None
    ) -> list[MemoryFact]:
        q = select(MemoryFact).order_by(MemoryFact.created_at.desc()).limit(limit)
        if session_id is not None:
            q = q.where(MemoryFact.session_id == session_id)
        result = await db.execute(q)
        return list(result.scalars().all())
