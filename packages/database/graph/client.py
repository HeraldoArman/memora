"""Async Neo4j driver singleton."""

from __future__ import annotations

from neo4j import AsyncGraphDatabase

_driver = None


async def init_driver(uri: str, user: str, password: str) -> None:
    """Create the global async driver. Call once at startup."""
    global _driver
    _driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    # Fail fast on bad credentials/URI rather than silently stalling.
    await _driver.verify_connectivity()


def get_driver():
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialized — call init_driver() at startup.")
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
    _driver = None


async def ping() -> bool:
    """Health check: return True if the driver can reach the database."""
    if _driver is None:
        return False
    try:
        await _driver.verify_connectivity()
        return True
    except Exception:
        return False
