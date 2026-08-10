"""Async Postgres engine + session factory.

One engine per process; sessionmaker hands out short-lived AsyncSession.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from postgres.base import Base  # noqa: F401  # ensure base imports for alembic target_metadata

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str, *, echo: bool = False) -> None:
    """Create the global engine + sessionmaker. Call once at startup."""
    global _engine, _sessionmaker
    _engine = create_async_engine(database_url, echo=echo, pool_pre_ping=True)
    _sessionmaker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


def get_engine():
    if _engine is None:
        raise RuntimeError("Postgres engine not initialized — call init_engine() at startup.")
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("Postgres sessionmaker not initialized — call init_engine() at startup.")
    return _sessionmaker


async def close_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
