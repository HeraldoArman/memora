"""add person_id column to memory_facts

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-11 05:10:00.000000

The person_id column was added to the MemoryFact model in a previous commit
but the migration was never updated. This adds it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("memory_facts", sa.Column("person_id", sa.String(length=64), nullable=True))
    op.create_index("ix_memory_facts_person_id", "memory_facts", ["person_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_memory_facts_person_id", table_name="memory_facts")
    op.drop_column("memory_facts", "person_id")
