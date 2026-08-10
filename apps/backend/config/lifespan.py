"""FastAPI lifespan — startup/shutdown of DB pools, Neo4j driver, FAISS index.

Init order on startup: Settings (raises loud if keys missing) → Postgres engine →
Neo4j driver → FAISS index load. Shutdown reverses it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from env import get_settings
from fastapi import FastAPI
from graph import client as neo4j_client
from vector.index import FaceIndex

from postgres import session as pg_session


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    # Postgres
    pg_session.init_engine(settings.database_url)

    # Neo4j
    await neo4j_client.init_driver(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)

    # FAISS — load existing index or start empty. FaceRepository wraps this (Phase 2).
    app.state.face_index = FaceIndex.load(
        settings.faiss_index_path, dim=settings.face_embedding_dim
    )

    try:
        yield
    finally:
        await pg_session.close_engine()
        await neo4j_client.close_driver()
