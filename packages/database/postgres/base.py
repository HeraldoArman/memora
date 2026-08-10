"""SQLAlchemy declarative base shared by all Postgres models."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root declarative base. Models register against this; Alembic autogenerates from it."""
