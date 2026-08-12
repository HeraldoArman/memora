"""Settings endpoint — key-value runtime config from Postgres."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from postgres.models import Setting
from postgres.session import get_sessionmaker

router = APIRouter()


@router.get("/settings")
async def list_settings() -> dict[str, str]:
    """All key-value settings as a flat dict."""
    sm = get_sessionmaker()
    async with sm() as db:
        result = await db.execute(select(Setting))
        return {s.key: s.value for s in result.scalars().all()}
