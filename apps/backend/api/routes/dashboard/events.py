"""Events endpoint — upcoming calendar events."""

from __future__ import annotations

from fastapi import APIRouter, Query

from services import EventService

router = APIRouter()

_service = EventService()


@router.get("/events/upcoming")
async def events_upcoming(limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    return await _service.upcoming(limit=limit)
