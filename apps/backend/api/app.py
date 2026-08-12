"""FastAPI application factory.

create_app() wires lifespan + routers. The root app.py exposes `app = create_app()`
so `uvicorn app:app --app-dir apps/backend` finds it.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from api.routes import health
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

    app.include_router(health.router)
    return app
