"""DB integration test — Python → Postgres + Neo4j + FAISS round-trip.

Minimal, not comprehensive: proves every repository method executes without a
runtime error and returns the expected shape. Run after `bun run db:start` +
`bun run db:migrate` (or point env vars at any live Postgres/Neo4j):

    uv run python scripts/verify/db_integration.py

This is the "integration is wired correctly" gate the CI runs — the same path
the app uses at runtime (SQLAlchemy async + asyncpg, async Neo4j driver, FAISS
IndexFlatIP). No Gemini/LiveKit/InsightFace — DB only, so it runs offline.

Coverage:
  - Postgres: ConversationRepo, TranscriptRepo, EventRepo, ReminderRepo,
    ShoppingRepo, SystemRepo (every public method exercised)
  - Neo4j:   PersonRepo + KnowledgeGraphRepo (upsert/get/relations/entity graph)
  - FAISS:   FaceRepository register/lookup/save/load + unknown rejection
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import numpy as np

# Ensure backend + shared packages importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from env import get_settings  # noqa: E402
from graph import client as neo4j_client  # noqa: E402
from graph import repository as graph_repo  # noqa: E402
from vector import repository as vector_repo  # noqa: E402

from postgres import session as pg_session  # noqa: E402
from postgres.models import (  # noqa: E402
    ConversationMessage,
    ConversationSession,
    Event,
    MemoryFact,
    Reminder,
    ShoppingItem,
    ShoppingList,
    SystemLog,
    Transcript,
)
from postgres.repositories import (  # noqa: E402
    ConversationRepo,
    EventRepo,
    FactRepo,
    ReminderRepo,
    ShoppingRepo,
    SystemRepo,
    TranscriptRepo,
)

_PASS = 0


def _ok(label: str) -> None:
    global _PASS
    _PASS += 1
    print(f"  ✔ {label}")


async def _postgres() -> None:
    print("[postgres]")
    sm = pg_session.get_sessionmaker()

    # --- ConversationRepo ---
    conv = ConversationRepo()
    async with sm() as db:
        s = await conv.create_session(db, summary="integration test")
        assert isinstance(s, ConversationSession) and s.id is not None
        _ok("conversation.create_session")

        await conv.end_session(db, s.id, summary="wrapped up")
        async with sm() as db2:
            ended = await db2.get(ConversationSession, s.id)
        assert ended is not None and ended.ended_at is not None
        _ok("conversation.end_session")

        m1 = await conv.add_message(db, session_id=s.id, role="user", content="Halo Asep")
        await conv.add_message(db, session_id=s.id, role="assistant", content="Halo!")
        assert isinstance(m1, ConversationMessage) and m1.content == "Halo Asep"
        _ok("conversation.add_message")

        msgs = await conv.list_messages(db, s.id)
        assert len(msgs) == 2 and msgs[0].role == "user"
        _ok("conversation.list_messages")

        recent = await conv.recent_sessions(db, limit=5)
        assert any(r.id == s.id for r in recent)
        _ok("conversation.recent_sessions")

    # --- TranscriptRepo ---
    tr = TranscriptRepo()
    async with sm() as db:
        t = await tr.add(db, session_id=s.id, text="test transcript", language="id", is_final=True)
        assert isinstance(t, Transcript) and t.text == "test transcript"
        _ok("transcript.add")
        ts = await tr.list_for_session(db, s.id)
        assert any(x.text == "test transcript" for x in ts)
        _ok("transcript.list_for_session")

    # --- EventRepo ---
    ev = EventRepo()
    now = datetime.now(UTC)
    async with sm() as db:
        e = await ev.create(
            db,
            title="Kontrol dokter",
            starts_at=now + timedelta(hours=1),
            description="klinik",
            location="RS",
            ends_at=None,
        )
        assert isinstance(e, Event) and e.title == "Kontrol dokter"
        _ok("event.create")
        got = await ev.get(db, e.id)
        assert got is not None and got.id == e.id
        _ok("event.get")
        upcoming = await ev.upcoming(db, after=now, limit=10)
        assert any(x.id == e.id for x in upcoming)
        _ok("event.upcoming")
        hits = await ev.search(db, "dokter")
        assert any(x.id == e.id for x in hits)
        _ok("event.search")
        await ev.delete(db, e.id)
        gone = await db.get(Event, e.id)
        assert gone is None
        _ok("event.delete")

    # --- ReminderRepo ---
    rm = ReminderRepo()
    async with sm() as db:
        r = await rm.create(db, title="Minum obat", due_at=now + timedelta(minutes=30), note="2x")
        assert isinstance(r, Reminder) and not r.completed
        _ok("reminder.create")
        got = await rm.get(db, r.id)
        assert got is not None
        _ok("reminder.get")
        upd = await rm.update(db, r.id, completed=True, note="ditegur anak")
        assert upd is not None and upd.completed and upd.note == "ditegur anak"
        _ok("reminder.update")
        found = await rm.search(db, "obat")
        assert any(x.id == r.id for x in found)
        _ok("reminder.search")
        # due_today/upcoming filter on ~completed — use a fresh, uncompleted reminder
        r2 = await rm.create(db, title="Minum obat lagi", due_at=now + timedelta(minutes=45))
        today = await rm.due_today(
            db, day_start=now - timedelta(minutes=5), day_end=now + timedelta(hours=24)
        )
        assert any(x.id == r2.id for x in today)
        _ok("reminder.due_today")
        up = await rm.upcoming(db, after=now, limit=5)
        assert any(x.id == r2.id for x in up)
        _ok("reminder.upcoming")
        await rm.delete(db, r2.id)
        ok = await rm.delete(db, r.id)
        assert ok and await db.get(Reminder, r.id) is None
        _ok("reminder.delete")

    # --- ShoppingRepo ---
    sp = ShoppingRepo()
    async with sm() as db:
        lst = await sp.get_or_create_default(db)
        assert isinstance(lst, ShoppingList)
        _ok("shopping.get_or_create_default")
        item = await sp.add_item(db, list_id=lst.id, name="Telur", quantity="6")
        assert isinstance(item, ShoppingItem) and item.name == "Telur"
        _ok("shopping.add_item")
        items = await sp.list_items(db, lst.id)
        assert any(i.id == item.id for i in items)
        _ok("shopping.list_items")
        found = await sp.find_item(db, list_id=lst.id, name="telur")
        assert found is not None and found.id == item.id
        _ok("shopping.find_item")
        checked = await sp.set_checked(db, item.id, True)
        assert checked is not None and checked.checked
        _ok("shopping.set_checked")
        gone = await sp.delete_item(db, item.id)
        assert gone and await db.get(ShoppingItem, item.id) is None
        _ok("shopping.delete_item")

    # --- SystemRepo ---
    sy = SystemRepo()
    async with sm() as db:
        entry = await sy.log(db, message="integration test", level="INFO", source="verify")
        assert isinstance(entry, SystemLog)
        _ok("system.log")
        await sy.set_setting(db, key="test_key", value="abc")
        val = await sy.get_setting(db, "test_key")
        assert val == "abc"
        _ok("system.set_setting/get_setting")
        await sy.set_setting(db, key="test_key", value="xyz")
        val2 = await sy.get_setting(db, "test_key")
        assert val2 == "xyz"
        _ok("system.set_setting (update)")

    # --- FactRepo (extracted memory facts) ---
    fr = FactRepo()
    async with sm() as db:
        n = await fr.add_many(
            db,
            facts=["Asep likes sushi", "Asep works at Tokopedia"],
            session_id=s.id,
            confidence=0.95,
        )
        assert n == 2
        _ok("fact.add_many")
        facts = await fr.list_recent(db, limit=10)
        assert any(f.fact == "Asep likes sushi" and f.session_id == s.id for f in facts)
        assert all(isinstance(f, MemoryFact) for f in facts)
        _ok("fact.list_recent")


async def _neo4j() -> None:
    print("[neo4j]")
    person_id = uuid4().hex
    name = f"Asep {person_id[:6]}"

    person_repo = graph_repo.PersonRepo()
    kg = graph_repo.KnowledgeGraphRepo()

    node = await person_repo.upsert_person(person_id=person_id, name=name, notes="integration")
    assert node.get("name") == name
    _ok("person.upsert_person")

    got = await person_repo.get_person(person_id)
    assert got is not None and got["name"] == name
    _ok("person.get_person")

    # entity + relationship + search
    e1 = await kg.upsert_entity(name="Tokopedia", category="Organization")
    assert e1.get("name") == "Tokopedia"
    _ok("kg.upsert_entity")

    rel = await kg.add_relation(
        person_id=person_id, name="Tokopedia", category="Organization", relationship="WORKS_AT"
    )
    assert rel.get("name") == "Tokopedia"
    _ok("kg.add_relation")

    hits = await kg.search_entity("Tokopedia")
    assert any(h.get("name") == "Tokopedia" for h in hits)
    _ok("kg.search_entity")

    # related people: KNOWS edge to a name-keyed Person node. add_relation merges
    # Person by name (no person_id) — assert the connected person shows up by name.
    budi = f"Budi {uuid4().hex[:6]}"
    await kg.add_relation(person_id=person_id, name=budi, category="Person", relationship="KNOWS")
    related = await person_repo.related_people(person_id)
    assert any(r.get("name") == budi for r in related), f"related={related}"
    _ok("person.related_people")

    # preferences: add a LIKES edge to Food node, then search_preferences
    await kg.add_relation(person_id=person_id, name="Sushi", category="Food", relationship="LIKES")
    prefs = await kg.search_preferences(person_id)
    assert any(p.get("name") == "Sushi" and p.get("likes") for p in prefs)
    _ok("kg.search_preferences")

    # entity_relationships: subgraph around the person
    graph = await kg.entity_relationships(name)
    assert isinstance(graph, dict) and "nodes" in graph and "edges" in graph
    _ok("kg.entity_relationships")


async def _faiss() -> None:
    print("[faiss]")
    settings = get_settings()
    rng = np.random.default_rng(7)
    repo = vector_repo.FaceRepository(
        vector_repo.FaceIndex(settings.face_embedding_dim),
        known_threshold=settings.face_match_threshold,
        possible_threshold=settings.face_possible_match_threshold,
    )
    assert repo.size == 0
    _ok("faiss.empty")

    emb = rng.normal(size=settings.face_embedding_dim)
    row = repo.register(emb, "person-1")
    assert row == 0
    _ok("faiss.register")

    lookup = repo.lookup(emb)
    assert lookup.is_known and lookup.person_id == "person-1"
    _ok("faiss.lookup (known)")

    unknown = rng.normal(size=settings.face_embedding_dim)
    bad = repo.lookup(unknown)
    assert not bad.is_known and not bad.is_possible
    _ok("faiss.lookup (unknown rejected)")

    # save/load round-trip preserves the sidecar mapping
    with TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "face_index.faiss")
        repo.save(path)
        loaded = vector_repo.FaceRepository.load(path)
        assert loaded.size == 1 and loaded.person_ids == ["person-1"]
        again = loaded.lookup(emb)
        assert again.is_known and again.person_id == "person-1"
    _ok("faiss.save/load round-trip")


async def main() -> None:
    settings = get_settings()

    pg_session.init_engine(settings.database_url)
    await neo4j_client.init_driver(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)

    try:
        await _postgres()
        await _neo4j()
        await _faiss()
    finally:
        await pg_session.close_engine()
        await neo4j_client.close_driver()

    print(f"\n✅ DB integration OK — {_PASS} checks passed (Postgres + Neo4j + FAISS)")


if __name__ == "__main__":
    asyncio.run(main())
