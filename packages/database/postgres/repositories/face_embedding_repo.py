"""Face embedding repository — Postgres-backed source of truth for the FAISS index."""

from __future__ import annotations

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from postgres.models import FaceEmbedding


class FaceEmbeddingRepo:
    """CRUD for face embeddings. The FAISS index is rebuilt from this table on startup."""

    async def save(self, db: AsyncSession, *, person_id: str, embedding: np.ndarray) -> None:
        row = FaceEmbedding(
            person_id=person_id, embedding=np.asarray(embedding, dtype=np.float32).tobytes()
        )
        db.add(row)
        await db.commit()

    async def load_all(self, db: AsyncSession) -> list[tuple[str, np.ndarray]]:
        result = await db.execute(select(FaceEmbedding).order_by(FaceEmbedding.created_at))
        rows = list(result.scalars().all())
        return [(r.person_id, np.frombuffer(r.embedding, dtype=np.float32)) for r in rows]
