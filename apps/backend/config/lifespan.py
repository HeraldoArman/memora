"""FastAPI lifespan — startup/shutdown of DB pools, Neo4j driver, FAISS index.

Init order on startup: Settings (raises loud if keys missing) → Postgres engine →
Neo4j driver → FAISS index load. Shutdown reverses it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from env import get_settings
from fastapi import FastAPI
from graph import client as neo4j_client
from vector.repository import FaceRepository

from postgres import session as pg_session

log = logging.getLogger(__name__)


def _upgrade_db() -> None:
    """Idempotent `alembic upgrade head` — the app's own connection works on
    Railway, so apply pending migrations at startup. Runs in a thread because
    env.py calls asyncio.run() and needs its own loop."""
    root = Path(__file__).resolve().parents[3]
    cfg = Config()
    cfg.set_main_option(
        "script_location",
        str(root / "packages/database/postgres/migrations"),
    )
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    # Postgres
    pg_session.init_engine(settings.database_url)
    await asyncio.to_thread(_upgrade_db)

    # Neo4j
    await neo4j_client.init_driver(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)

    # FAISS — rebuild from Postgres (durable store). The .faiss file is a local
    # cache for dev; on Railway both backend and worker use Postgres as source of
    # truth so they share face registrations without a shared volume.
    app.state.face_repo = await FaceRepository.from_db(
        known_threshold=settings.face_match_threshold,
        possible_threshold=settings.face_possible_match_threshold,
        dim=settings.face_embedding_dim,
    )
    app.state.face_index = app.state.face_repo.index  # kept for admin/debug routes
    log.info(
        "face repository ready: %d embedding(s) from DB",
        app.state.face_repo.size,
    )

    try:
        yield
    finally:
        await pg_session.close_engine()
        await neo4j_client.close_driver()
