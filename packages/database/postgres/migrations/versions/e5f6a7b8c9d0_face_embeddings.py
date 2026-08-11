"""add face_embeddings table

Revision ID: e5f6a7b8c9d0
Revises: d5e6f7a8b9c0
Create Date: 2026-08-11 05:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "face_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_face_embeddings_person_id"), "face_embeddings", ["person_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_face_embeddings_person_id"), table_name="face_embeddings")
    op.drop_table("face_embeddings")
