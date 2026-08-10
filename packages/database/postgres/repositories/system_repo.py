"""System log + key-value setting repository."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from postgres.models import Setting, SystemLog


class SystemRepo:
    """Logs + runtime key-value settings."""

    async def log(
        self, db: AsyncSession, *, message: str, level: str = "INFO", source: str | None = None
    ) -> SystemLog:
        entry = SystemLog(level=level, source=source, message=message)
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry

    async def get_setting(self, db: AsyncSession, key: str) -> str | None:
        s = await db.get(Setting, key)
        return s.value if s is not None else None

    async def set_setting(self, db: AsyncSession, *, key: str, value: str) -> Setting:
        s = await db.get(Setting, key)
        if s is None:
            s = Setting(key=key, value=value)
            db.add(s)
        else:
            s.value = value
        await db.commit()
        await db.refresh(s)
        return s
