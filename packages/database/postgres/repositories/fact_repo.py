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
        confidences: list[float] | None = None,
    ) -> int:
        """Persist facts. `confidence` applies to all; `confidences` (parallel to
        `facts`) overrides per-fact when both shapes are needed (first-person boost is
        per-fact, not per-turn). When `confidences` is given it must match len(facts)."""
        if confidences is not None and len(confidences) != len(facts):
            raise ValueError("confidences must align with facts")
        rows = [
            MemoryFact(
                session_id=session_id,
                fact=f,
                category=category,
                confidence=confidences[i] if confidences is not None else confidence,
            )
            for i, f in enumerate(facts)
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
