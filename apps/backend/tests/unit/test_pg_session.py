"""Unit tests — Postgres engine/session factory (packages/database/postgres/session).

No DB connection needed: init_engine only constructs the engine (lazy). We verify the
module-global lifecycle guards raise before init and clear after close.
"""

from __future__ import annotations

import pytest

import postgres.session as pg


@pytest.fixture(autouse=True)
def _clean_pg_state():
    """Ensure no global engine leaks between tests."""
    import asyncio

    try:
        asyncio.run(pg.close_engine())
    except RuntimeError:  # no loop in some envs
        pass
    yield
    import asyncio

    try:
        asyncio.run(pg.close_engine())
    except RuntimeError:
        pass


class TestPgSession:
    def test_get_sessionmaker_raises_before_init(self) -> None:
        with pytest.raises(RuntimeError, match="not initialized"):
            pg.get_sessionmaker()

    def test_get_engine_raises_before_init(self) -> None:
        with pytest.raises(RuntimeError, match="not initialized"):
            pg.get_engine()

    def test_init_then_get(self) -> None:
        pg.init_engine("postgresql+asyncpg://u:p@localhost:5432/db")
        assert pg.get_engine() is not None
        assert pg.get_sessionmaker() is not None

    def test_close_clears_state(self) -> None:
        pg.init_engine("postgresql+asyncpg://u:p@localhost:5432/db")
        import asyncio

        asyncio.run(pg.close_engine())
        with pytest.raises(RuntimeError):
            pg.get_sessionmaker()

    def test_init_idempotent(self) -> None:
        pg.init_engine("postgresql+asyncpg://u:p@localhost:5432/db")
        pg.init_engine("postgresql+asyncpg://u:p@localhost:5432/db2")
        assert pg.get_sessionmaker() is not None
