"""FastAPI lifespan — startup/shutdown of DB pools, Neo4j driver, FAISS index.

Init order on startup: Settings (raises loud if keys missing) → Postgres engine →
Neo4j driver → FAISS index load. Shutdown reverses it.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from env import get_settings
from fastapi import FastAPI
from graph import client as neo4j_client
from vector.repository import FaceRepository

from postgres import session as pg_session

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    # Postgres
    pg_session.init_engine(settings.database_url)

    # Neo4j
    await neo4j_client.init_driver(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)

    # FAISS — load existing index + person_id sidecar or start empty (Phase 2 wiring).
    # FaceRepository.load builds the index AND the person_id↔row map from the sidecar,
    # so face identity works in this process (admin API). The livekit-agent worker builds
    # its own copy in RoomSession.create (different process, no lifespan).
    app.state.face_repo = FaceRepository.load(
        settings.faiss_index_path,
        known_threshold=settings.face_match_threshold,
        possible_threshold=settings.face_possible_match_threshold,
    )
    app.state.face_index = app.state.face_repo.index  # kept for admin/debug routes
    log.info(
        "face repository ready: %d embedding(s) at %s",
        app.state.face_repo.size,
        settings.faiss_index_path,
    )

    try:
        yield
    finally:
        await pg_session.close_engine()
        await neo4j_client.close_driver()
