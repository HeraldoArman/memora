"""Face embeddings — the persistent source of truth for the FAISS face index.

FAISS itself is an in-process index file (ephemeral on Railway without a volume).
This table is the durable store: register_face writes here, and both the backend
and worker rebuild their in-process FAISS index from this table on startup.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from postgres.base import Base


class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    person_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 512-d float32 = 2048 bytes, stored as raw bytes for compactness.
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
