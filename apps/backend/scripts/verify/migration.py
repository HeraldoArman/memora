"""Migration test — verify `alembic upgrade head` applied the full schema.

Connects to the live Postgres (via Settings) and asserts:
  1. the alembic_version table holds the head revision,
  2. every table the models declare exists.

Run after `bun run db:migrate` (or any `alembic upgrade head`):

    uv run python scripts/verify/migration.py

This is the CI "migration test" gate: a fresh Postgres service, upgrade head,
then this script proves the migration actually created the schema the code
expects. No app code beyond models — pure schema check.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import inspect, text

# Ensure backend + shared packages importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from env import get_settings  # noqa: E402

from postgres import session as pg_session  # noqa: E402

# Head revision from packages/database/postgres/migrations/versions/.
HEAD_REVISION = "89310c8b2c74"

EXPECTED_TABLES = {
    "conversation_sessions",
    "conversation_messages",
    "transcripts",
    "events",
    "reminders",
    "shopping_lists",
    "shopping_items",
    "settings",
    "system_logs",
    "alembic_version",
}


async def main() -> None:
    settings = get_settings()
    pg_session.init_engine(settings.database_url)

    try:
        engine = pg_session.get_engine()
        async with engine.connect() as conn:
            # 1. alembic_version points at head
            row = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            assert row == HEAD_REVISION, (
                f"alembic_version={row!r}, expected {HEAD_REVISION!r} — run `bun run db:migrate`"
            )
            print(f"  ✔ alembic_version = {row}")

            # 2. every declared table exists (list inside run_sync — inspect is lazy)
            def _table_names(sync_conn):
                return set(inspect(sync_conn).get_table_names())

            actual = await conn.run_sync(_table_names)
            missing = EXPECTED_TABLES - actual
            assert not missing, f"missing tables after migration: {sorted(missing)}"
            print(f"  ✔ {len(actual)} tables present: {', '.join(sorted(actual))}")
    finally:
        await pg_session.close_engine()

    print("\n✅ Migration OK — schema matches head revision")


if __name__ == "__main__":
    asyncio.run(main())
