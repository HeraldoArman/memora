"""Extracted memory facts — raw statement strings from the extraction pipeline.

The extraction output (ExtractedKnowledge.facts) holds plain-statement strings (e.g.
"Asep likes sushi") that don't map cleanly onto a graph edge. They're persisted here as
the relational long-term memory alongside the graph (Neo4j) + episodic (conversation)
stores. Single implicit device → no user FK.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from postgres.base import Base


class MemoryFact(Base):
    __tablename__ = "memory_facts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # NULL when a fact is persisted without a conversation session.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    fact: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
