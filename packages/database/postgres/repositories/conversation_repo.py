"""Conversation session + message repository.

Episodic operational records. Sessions assume implicit single device (no user FK).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from postgres.models import ConversationMessage, ConversationSession


class ConversationRepo:
    """CRUD for conversation sessions + messages."""

    async def create_session(
        self, db: AsyncSession, *, summary: str | None = None
    ) -> ConversationSession:
        session = ConversationSession(summary=summary)
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def end_session(
        self, db: AsyncSession, session_id: UUID, *, summary: str | None = None
    ) -> None:
        session = await db.get(ConversationSession, session_id)
        if session is None:
            return
        if summary is not None:
            session.summary = summary
        from utils.time_ids import now_utc

        session.ended_at = now_utc()
        await db.commit()

    async def add_message(
        self, db: AsyncSession, *, session_id: UUID, role: str, content: str
    ) -> ConversationMessage:
        msg = ConversationMessage(session_id=session_id, role=role, content=content)
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg

    async def list_messages(
        self, db: AsyncSession, session_id: UUID, *, limit: int = 100
    ) -> list[ConversationMessage]:
        result = await db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.session_id == session_id)
            .order_by(ConversationMessage.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def recent_sessions(
        self, db: AsyncSession, *, limit: int = 10
    ) -> list[ConversationSession]:
        result = await db.execute(
            select(ConversationSession).order_by(ConversationSession.started_at.desc()).limit(limit)
        )
        return list(result.scalars().all())
