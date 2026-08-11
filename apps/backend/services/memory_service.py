"""Memory service — episodic (Postgres conversation) retrieval.

Semantic memory lives in Neo4j (see knowledge_service). This wraps the conversation repo
for recent-history / timeline queries. Ranking + fusion arrive in Phase 5 (Context Engine).
"""

from __future__ import annotations

from uuid import UUID

from postgres.repositories import ConversationRepo, FactRepo, TranscriptRepo
from postgres.session import get_sessionmaker


class MemoryService:
    """Episodic recall over conversation sessions + transcripts + extracted facts."""

    def __init__(
        self,
        conversation_repo: ConversationRepo | None = None,
        transcript_repo: TranscriptRepo | None = None,
        fact_repo: FactRepo | None = None,
    ) -> None:
        self.conversation_repo = conversation_repo or ConversationRepo()
        self.transcript_repo = transcript_repo or TranscriptRepo()
        self.fact_repo = fact_repo or FactRepo()

    async def recent_memories(self, *, limit: int = 10) -> list[dict]:
        """Recent conversation summaries as lightweight memory records."""
        sm = get_sessionmaker()
        async with sm() as db:
            sessions = await self.conversation_repo.recent_sessions(db, limit=limit)
            return [
                {
                    "session_id": str(s.id),
                    "started_at": s.started_at.isoformat() if s.started_at else None,
                    "summary": s.summary,
                }
                for s in sessions
            ]

    async def conversation_history(self, session_id: UUID, *, limit: int = 100) -> list[dict]:
        sm = get_sessionmaker()
        async with sm() as db:
            msgs = await self.conversation_repo.list_messages(db, session_id, limit=limit)
            return [
                {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
                for m in msgs
            ]

    async def transcripts(self, session_id: UUID, *, limit: int = 200) -> list[dict]:
        sm = get_sessionmaker()
        async with sm() as db:
            ts = await self.transcript_repo.list_for_session(db, session_id, limit=limit)
            return [{"text": t.text, "is_final": t.is_final, "language": t.language} for t in ts]

    async def start_session(self, *, summary: str | None = None) -> str:
        sm = get_sessionmaker()
        async with sm() as db:
            s = await self.conversation_repo.create_session(db, summary=summary)
            return str(s.id)

    async def add_message(self, *, session_id: UUID, role: str, content: str) -> str:
        sm = get_sessionmaker()
        async with sm() as db:
            m = await self.conversation_repo.add_message(
                db, session_id=session_id, role=role, content=content
            )
            return str(m.id)

    async def add_facts(
        self,
        *,
        facts: list[str],
        session_id: UUID | None = None,
        person_id: str | None = None,
        confidence: float | None = None,
        confidences: list[float] | None = None,
    ) -> int:
        """Persist extracted fact statements. No-op when empty.

        `confidences` (per-fact) takes precedence over the scalar `confidence` — used
        for the first-person provenance boost, which is per-fact, not per-turn.
        """
        if not facts:
            return 0
        sm = get_sessionmaker()
        async with sm() as db:
            return await self.fact_repo.add_many(
                db,
                facts=facts,
                session_id=session_id,
                person_id=person_id,
                confidence=confidence,
                confidences=confidences,
            )

    async def link_facts_to_person(self, *, session_id: UUID, person_id: str) -> int:
        """Retroactively link orphan facts from the current conversation to a person.

        Scoped to the last ~10 minutes so 24/7 sessions don't mix up facts from
        different conversation partners throughout the day.
        """
        sm = get_sessionmaker()
        async with sm() as db:
            return await self.fact_repo.link_recent_orphan_facts(
                db, session_id=session_id, person_id=person_id
            )
