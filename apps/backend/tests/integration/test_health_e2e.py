"""E2E tests — FastAPI app through the full ASGI stack against live stores.

Drives the real lifespan (Postgres engine + Neo4j driver + FAISS load) and hits
/health over HTTP. This is the thinnest real e2e surface (only /health is wired),
but it proves the app boots, the lifespan wiring works, and the health route
reports correctly against live backing services.

Marked `integration`: requires live Postgres + Neo4j (`bun run db:start`).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _asyncpg_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@pytest.fixture
async def app_lifespan():
    """Boot a real FastAPI app through its lifespan against the live DBs.

    Uses a non-persistent FAISS path so the health route sees an empty index
    (we don't want to load the real production index file). Skips if DBs down.
    """
    from graph import client as graph_client

    from api.app import create_app
    from postgres import session as pg

    # Reuse the integration conftest's DB env (already loaded from .env)
    db_url = _asyncpg_url(os.environ["DATABASE_URL"])
    pg.init_engine(db_url)
    try:
        async with pg.get_engine().begin() as conn:
            from postgres.base import Base

            await conn.run_sync(Base.metadata.create_all)
        await graph_client.init_driver(
            os.environ["NEO4J_URI"], os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]
        )
    except Exception as e:  # noqa: BLE001
        await pg.close_engine()
        pytest.skip(f"DBs unavailable: {type(e).__name__}: {e}")

    # Point FAISS at a temp path so lifespan loads an empty index (no side effects
    # on the real index file the worker/admin API uses).
    import tempfile

    tmpfaiss = Path(tempfile.mkdtemp()) / "e2e_face_index.faiss"
    os.environ["FAISS_INDEX_PATH"] = str(tmpfaiss)
    from env import get_settings

    get_settings.cache_clear()

    app = create_app()
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    # Run the lifespan: startup inits engine/driver/index, shutdown closes them.
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Trigger lifespan manually — ASGITransport doesn't run it automatically.
        from config.lifespan import lifespan

        async with lifespan(app):
            yield client

    get_settings.cache_clear()
    await graph_client.close_driver()
    await pg.close_engine()


class TestHealthE2E:
    async def test_health_ok_with_live_stores(self, app_lifespan) -> None:
        """All backing services up → 200, status ok, each dep reports ok."""
        resp = await app_lifespan.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["postgres"] == "ok"
        assert body["neo4j"] == "ok"
        # FAISS loaded empty (temp path) → ntotal=0
        assert body["faiss"].startswith("ok:ntotal=")

    async def test_health_body_shape(self, app_lifespan) -> None:
        """Health response always carries the four expected keys."""
        resp = await app_lifespan.get("/health")
        body = resp.json()
        assert set(body) >= {"status", "postgres", "neo4j", "faiss"}


class TestHealthDegradedE2E:
    """Health route must report 503 (not crash) when a backing service is down.
    We can't easily kill Postgres mid-test, so we verify the route's error path
    by hitting it after lifespan shutdown — stores are closed → degraded."""

    async def test_health_after_shutdown_reports_degraded(self) -> None:
        from graph import client as graph_client
        from httpx import ASGITransport, AsyncClient

        from api.app import create_app

        # Ensure stores are NOT initialized (close any leftover from prior tests)
        from postgres import session as pg

        await pg.close_engine()
        await graph_client.close_driver()

        app = create_app()
        transport = ASGITransport(app=app)
        # No lifespan → app.state.face_index is unset → faiss reports "unloaded",
        # pg/neo4j are uninitialized → degraded. The route must never raise.
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["faiss"] == "unloaded"
        assert body["postgres"].startswith("error:")
        assert body["neo4j"] == "error"
