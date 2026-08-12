"""Reminders endpoint — today + upcoming reminders."""

from __future__ import annotations

from fastapi import APIRouter, Query

from services import ReminderService

router = APIRouter()

_service = ReminderService()


@router.get("/reminders/today")
async def reminders_today() -> list[dict]:
    return await _service.today()


@router.get("/reminders/upcoming")
async def reminders_upcoming(limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    return await _service.upcoming(limit=limit)
