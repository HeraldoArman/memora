"""Conversations endpoint — session list + message history."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from postgres.repositories import ConversationRepo
from postgres.session import get_sessionmaker

router = APIRouter()

_repo = ConversationRepo()


@router.get("/conversations")
async def list_conversations(limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    """Recent conversation sessions, newest first."""
    sm = get_sessionmaker()
    async with sm() as db:
        sessions = await _repo.recent_sessions(db, limit=limit)
        return [
            {
                "id": str(s.id),
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                "summary": s.summary,
            }
            for s in sessions
        ]


@router.get("/conversations/{session_id}/messages")
async def get_messages(session_id: UUID, limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    """All messages in a conversation session."""
    sm = get_sessionmaker()
    async with sm() as db:
        msgs = await _repo.list_messages(db, session_id, limit=limit)
        return [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msgs
        ]
