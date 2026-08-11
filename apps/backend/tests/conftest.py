"""Shared test setup — required env defaults + reusable fakes.

Unit tests must not need a live DB / Gemini / LiveKit. This module:

  1. Sets default values for Settings' required vars (setdefault → a real
     apps/backend/.env or CI env still wins) so importing `env` doesn't raise.
  2. Exposes the `settings` fixture that clears get_settings()'s lru_cache so a
     test can re-point thresholds without cross-test pollution.

Integration tests live in tests/integration and are marked `integration`; they
need live Postgres + Neo4j (bun run db:start) and skip themselves otherwise.
"""

from __future__ import annotations

import os

import pytest

# Required Settings fields (no default → ValidationError at import). setdefault so
# real env/.env overrides win; values here match docker-compose + CI.
_REQUIRED_ENV = {
    "LIVEKIT_URL": "wss://ci.livekit.cloud",
    "LIVEKIT_API_KEY": "dummy",
    "LIVEKIT_API_SECRET": "dummy",
    "GEMINI_API_KEY": "dummy",
    "DATABASE_URL": "postgresql+asyncpg://postgres:password@localhost:5432/memora",
    "NEO4J_URI": "bolt://localhost:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "memora",
}

for _k, _v in _REQUIRED_ENV.items():
    os.environ.setdefault(_k, _v)


@pytest.fixture
def settings():
    """Fresh Settings singleton; clears get_settings cache before + after."""
    from env import get_settings

    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def face_embedding():
    """A deterministic 512-d embedding (unit tests only — no model load)."""
    import numpy as np
    from env import get_settings

    return np.zeros(get_settings().face_embedding_dim, dtype=np.float32)
