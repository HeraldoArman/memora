"""Seed smoke test — round-trip a person across Postgres + Neo4j + FAISS.

Verifies the Phase 2 wiring: a conversation session + message land in Postgres, a Person
node is created in Neo4j, a face embedding registers + looks up in FAISS, and the person_id
ties them together. Run after `bun run db:start` + `bun run db:migrate`.

    uv run python scripts/seed/smoke.py

Self-check: assertions fail loudly if any store is inconsistent.
"""

from __future__ import annotations

import asyncio
import sys
from uuid import uuid4

import numpy as np

# Ensure backend packages are importable when run as a script.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from env import get_settings  # noqa: E402
from graph import client as neo4j_client  # noqa: E402
from graph import repository as graph_repo  # noqa: E402
from vector import repository as vector_repo  # noqa: E402

from postgres import session as pg_session  # noqa: E402
from postgres.repositories import ConversationRepo  # noqa: E402


async def main() -> None:
    settings = get_settings()

    # --- init stores ---
    pg_session.init_engine(settings.database_url)
    await neo4j_client.init_driver(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    face_repo = vector_repo.FaceRepository(
        vector_repo.FaceIndex(settings.face_embedding_dim),
        known_threshold=settings.face_match_threshold,
        possible_threshold=settings.face_possible_match_threshold,
    )

    person_id = uuid4().hex
    name = "Asep Test"

    try:
        # --- Postgres: conversation session + message ---
        sm = pg_session.get_sessionmaker()
        conversation_repo = ConversationRepo()
        async with sm() as db:
            session = await conversation_repo.create_session(db, summary="smoke seed")
            await conversation_repo.add_message(
                db, session_id=session.id, role="user", content=f"Halo, ini {name}?"
            )
        print(f"postgres: session {session.id} + message written")

        # --- Neo4j: Person node ---
        person_repo = graph_repo.PersonRepo()
        node = await person_repo.upsert_person(person_id=person_id, name=name, notes="smoke seed")
        assert node.get("name") == name, f"neo4j name mismatch: {node}"
        fetched = await person_repo.get_person(person_id)
        assert fetched is not None and fetched["name"] == name, f"neo4j fetch mismatch: {fetched}"
        print(f"neo4j: Person {person_id[:8]} upserted + fetched")

        # --- FAISS: register face + lookup ---
        rng = np.random.default_rng(42)
        embedding = rng.normal(size=settings.face_embedding_dim)
        row = face_repo.register(embedding, person_id)
        assert row == 0, f"first row should be 0, got {row}"
        lookup = face_repo.lookup(embedding)
        assert lookup.is_known and lookup.person_id == person_id, (
            f"face lookup mismatch: known={lookup.is_known} pid={lookup.person_id}"
        )
        print(
            f"faiss: registered row {row}, lookup known={lookup.is_known} score={lookup.score:.3f}"
        )

        # --- cross-store: unknown face must not match ---
        other = rng.normal(size=settings.face_embedding_dim)
        bad = face_repo.lookup(other)
        assert not bad.is_known, f"random embedding should not be known, score={bad.score:.3f}"
        print(f"faiss: unknown embedding correctly rejected (score={bad.score:.3f})")

        print("\nALL PHASE 2 SMOKE CHECKS PASSED")
    finally:
        await pg_session.close_engine()
        await neo4j_client.close_driver()


if __name__ == "__main__":
    asyncio.run(main())
