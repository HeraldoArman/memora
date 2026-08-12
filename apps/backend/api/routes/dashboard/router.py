"""Dashboard API router — caregiver admin endpoints.

All endpoints are read-only (GET) and expose the existing services layer.
No auth — the dashboard is a local caregiver tool (same posture as the
device harness). Add auth before exposing publicly.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.routes.dashboard import (
    conversations,
    events,
    graph,
    health,
    memories,
    persons,
    reminders,
    settings,
    shopping,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
router.include_router(graph.router)
router.include_router(persons.router)
router.include_router(memories.router)
router.include_router(conversations.router)
router.include_router(reminders.router)
router.include_router(events.router)
router.include_router(shopping.router)
router.include_router(settings.router)
router.include_router(health.router)
