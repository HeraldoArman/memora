"""Transcript repository — raw STT output."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from postgres.models import Transcript


class TranscriptRepo:
    """Append-only transcripts keyed by session."""

    async def add(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        text: str,
        language: str | None = None,
        is_final: bool = True,
    ) -> Transcript:
        t = Transcript(session_id=session_id, text=text, language=language, is_final=is_final)
        db.add(t)
        await db.commit()
        await db.refresh(t)
        return t

    async def list_for_session(
        self, db: AsyncSession, session_id: UUID, *, limit: int = 200
    ) -> list[Transcript]:
        result = await db.execute(
            select(Transcript)
            .where(Transcript.session_id == session_id)
            .order_by(Transcript.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())
