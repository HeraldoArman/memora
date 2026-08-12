"""FastAPI application factory.

create_app() wires lifespan + routers. The root app.py exposes `app = create_app()`
so `uvicorn app:app --app-dir apps/backend` finds it.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import health, media
from api.routes.dashboard import router as dashboard_router
from config.lifespan import lifespan
from config.logging import setup_logging

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build the FastAPI app. Settings validation runs in lifespan; a missing
    required key raises a clear ValidationError at startup."""
    setup_logging(log_file="logs/backend.log")
    log.info("create_app(): FastAPI assembly starting")

    app = FastAPI(
        title="Memora",
        description="Backend brain for the Memora smart-glasses memory assistant.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # ponytail: open CORS for the local Next.js dashboard. Restrict origins
    # before deploying publicly.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(media.router)
    app.include_router(dashboard_router)
    return app
