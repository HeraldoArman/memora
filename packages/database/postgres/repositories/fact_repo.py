"""Extracted memory facts repository (raw statement strings)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from postgres.models import MemoryFact

# How far back to look for orphan facts when retroactively linking.
# 24/7 glasses mean one session can span the entire day — linking ALL orphan
# facts from the session would mix up facts from different conversation partners.
# This window scopes the link to facts from roughly the last conversation.
_ORPHAN_LINK_WINDOW = timedelta(minutes=10)


class FactRepo:
    """CRUD for extracted memory facts."""

    async def add_many(
        self,
        db: AsyncSession,
        *,
        facts: list[str],
        session_id: UUID | None = None,
        person_id: str | None = None,
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
                person_id=person_id,
                fact=f,
                category=category,
                confidence=confidences[i] if confidences is not None else confidence,
            )
            for i, f in enumerate(facts)
        ]
        db.add_all(rows)
        await db.commit()
        return len(rows)

    async def link_recent_orphan_facts(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        person_id: str,
        window: timedelta = _ORPHAN_LINK_WINDOW,
    ) -> int:
        """Retroactively link orphan facts (person_id IS NULL) from a session to a person,
        scoped to the last `window` of time.

        24/7 glasses mean one session can span hours — linking ALL orphan facts would mix
        facts from different conversation partners. This window scopes the link to facts
        from roughly the current conversation partner.
        Returns the number of rows updated.
        """
        cutoff = datetime.now(UTC) - window
        result = await db.execute(
            update(MemoryFact)
            .where(
                MemoryFact.session_id == session_id,
                MemoryFact.person_id.is_(None),
                MemoryFact.created_at >= cutoff,
            )
            .values(person_id=person_id)
        )
        await db.commit()
        return result.rowcount

    async def list_recent(
        self,
        db: AsyncSession,
        *,
        limit: int = 50,
        session_id: UUID | None = None,
        person_id: str | None = None,
    ) -> list[MemoryFact]:
        q = select(MemoryFact).order_by(MemoryFact.created_at.desc()).limit(limit)
        if session_id is not None:
            q = q.where(MemoryFact.session_id == session_id)
        if person_id is not None:
            q = q.where(MemoryFact.person_id == person_id)
        result = await db.execute(q)
        return list(result.scalars().all())
