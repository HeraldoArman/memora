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


def _head_revision() -> str:
    """Current alembic head, derived from the migrations dir (never goes stale).

    Hardcoding the head revision meant every new migration silently broke this
    check until someone remembered to bump the constant. Reading it from the
    versions dir via ScriptDirectory makes the assert self-updating.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    # apps/backend/scripts/verify/migration.py → repo root (parents[4]) → packages/database
    repo_root = Path(__file__).resolve().parents[4]
    migrations = repo_root / "packages" / "database" / "postgres" / "migrations"
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations))
    return ScriptDirectory.from_config(cfg).get_current_head()


HEAD_REVISION = _head_revision()

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
    "memory_facts",
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
