"""Health route — pings Postgres, Neo4j, FAISS."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from graph import client as neo4j_client
from sqlalchemy import text

from postgres import session as pg_session

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    """Report liveness of each backing service. 200 if all deps up; 503 if any
    backing service is down so load balancers + healthchecks don't route to a node
    that can't actually serve. Individual services report their own status so a
    partial outage is still visible in the body."""
    status: dict[str, str | int] = {"status": "ok"}

    # Postgres
    try:
        async with pg_session.get_sessionmaker()() as db:
            await db.execute(text("SELECT 1"))
        status["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001 — health must never crash
        status["postgres"] = f"error: {exc.__class__.__name__}"
        status["status"] = "degraded"

    # Neo4j
    if await neo4j_client.ping():
        status["neo4j"] = "ok"
    else:
        status["neo4j"] = "error"
        status["status"] = "degraded"

    # FAISS (in-process)
    idx = getattr(request.app.state, "face_index", None)
    status["faiss"] = f"ok:ntotal={idx.size}" if idx is not None else "unloaded"

    code = 503 if status["status"] == "degraded" else 200
    return JSONResponse(content=status, status_code=code)
