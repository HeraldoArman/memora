"""add unique constraint on shopping_lists.title

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-08-10 14:00:00.000000

Guarantees one default list. get_or_create_default uses INSERT ... ON CONFLICT
DO NOTHING on title, which needs this constraint to target.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: str | Sequence[str] | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Clean any pre-existing duplicate titles before adding the constraint, so the
    # migration succeeds on DBs where the TOCTOU race already produced two rows.
    op.execute(
        "DELETE FROM shopping_lists a USING shopping_lists b "
        "WHERE a.title = b.title AND a.id > b.id"
    )
    op.create_unique_constraint("uq_shopping_lists_title", "shopping_lists", ["title"])


def downgrade() -> None:
    op.drop_constraint("uq_shopping_lists_title", "shopping_lists", type_="unique")
