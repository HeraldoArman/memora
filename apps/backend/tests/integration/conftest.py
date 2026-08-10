"""Integration test setup — live Postgres + Neo4j + FAISS.

Tests skip themselves when the DBs are unreachable (`bun run db:start` brings them up).
Local creds come from apps/backend/.env (matches docker-compose); CI passes its own env
through (apps/backend/.env is gitignored, so absence there = use CI env).

Each test gets a truncated Postgres (clean slate); the Neo4j graph + FAISS are left
intact and tests use unique names/ids to avoid collisions.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# apps/backend/tests/integration/conftest.py → parents[2] = apps/backend
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_DB_ENV = {"DATABASE_URL", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"}

if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        if _k.strip() in _DB_ENV:
            os.environ[_k.strip()] = _v.strip()


_POSTGRES_TABLES = [
    "conversation_messages",
    "transcripts",
    "memory_facts",
    "conversation_sessions",
    "reminders",
    "events",
    "shopping_items",
    "shopping_lists",
    "system_logs",
    "settings",
]


def _asyncpg_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@pytest.fixture(autouse=True)
async def db_backend():
    """Init the Postgres engine (create_all) + Neo4j driver. Skip if either is down.

    Function-scoped on purpose: pytest-asyncio auto mode runs each test in its own event
    loop, so the engine/driver must be created in the same loop that uses them.
    """
    from graph import client as graph_client

    from postgres import models  # noqa: F401  # register all tables on Base
    from postgres import session as pg
    from postgres.base import Base

    pg.init_engine(_asyncpg_url(os.environ["DATABASE_URL"]))
    try:
        async with pg.get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await graph_client.init_driver(
            os.environ["NEO4J_URI"],
            os.environ["NEO4J_USER"],
            os.environ["NEO4J_PASSWORD"],
        )
    except Exception as e:  # noqa: BLE001 — DB down → skip, don't fail the suite
        await pg.close_engine()
        pytest.skip(f"DBs unavailable: {type(e).__name__}: {e}")
    yield
    await graph_client.close_driver()
    await pg.close_engine()


@pytest.fixture(autouse=True)
async def clean_pg(db_backend):
    """Truncate Postgres before each test so relational tests are isolated."""
    from sqlalchemy import text

    from postgres.session import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as db:
        await db.execute(text(f"TRUNCATE {', '.join(_POSTGRES_TABLES)} RESTART IDENTITY CASCADE"))
        await db.commit()
    yield
