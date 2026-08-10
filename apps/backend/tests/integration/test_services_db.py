"""Integration tests — every service against real Postgres + Neo4j + FAISS.

Marked `integration`: requires `bun run db:start` (or any Postgres+Neo4j on the URLs
in apps/backend/.env). Skips itself when unreachable. Postgres is truncated before each
test (conftest); the Neo4j graph is left intact — tests use unique names/person_ids.

FAISS is a real in-memory index here (no model download); save/load exercises the
on-disk serialization.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import numpy as np
import pytest
from vector.index import FaceIndex
from vector.repository import FaceRepository

from postgres.repositories import TranscriptRepo
from postgres.session import get_sessionmaker
from services import (
    EventService,
    FaceService,
    KnowledgeService,
    MemoryService,
    PersonService,
    ReminderService,
    ShoppingService,
)


def _name(prefix: str) -> str:
    """Unique name/identifier so Neo4j tests never collide across runs."""
    return f"{prefix}_{uuid4().hex[:8]}"


def _vec(axis: int) -> np.ndarray:
    """Deterministic 512-d unit vector along `axis` — mutually orthogonal for distinct axes."""
    v = np.zeros(512, dtype=np.float32)
    v[axis] = 1.0
    return v


class TestPersonService:
    async def test_register_get_update(self) -> None:
        svc = PersonService()
        pid = _name("pid")
        created = await svc.register_person(name="Asep Surya", person_id=pid)
        assert created["name"] == "Asep Surya"
        got = await svc.get_person(pid)
        assert got["name"] == "Asep Surya"

        updated = await svc.update_person(person_id=pid, notes="suka kopi")
        assert updated["notes"] == "suka kopi"
        assert (await svc.get_person(pid))["notes"] == "suka kopi"

    async def test_update_missing_returns_none(self) -> None:
        svc = PersonService()
        assert await svc.update_person(person_id=_name("missing")) is None

    async def test_search_by_name_substring(self) -> None:
        svc = PersonService()
        name = _name("Asep")
        await svc.register_person(name=name, person_id=_name("pid"))
        hits = await svc.search_by_name(name[: len("Asep") + 3])
        assert any(h["name"] == name for h in hits)

    async def test_related_people(self) -> None:
        svc = PersonService()
        a, b = _name("a"), _name("b")
        await svc.register_person(name="Ana", person_id=a)
        await svc.register_person(name="Budi", person_id=b)
        # link Budi into Ana's graph (KNOWS) — Budi is also a Person node
        await svc.kg_repo.add_relation(
            person_id=a, name="Budi", category="Person", relationship="KNOWS"
        )
        related = await svc.related_people(a)
        assert any(r["name"] == "Budi" for r in related)

    async def test_register_face_requires_repo(self) -> None:
        with pytest.raises(RuntimeError, match="configure"):
            await PersonService().register_face(_vec(0), _name("pid"))

    async def test_search_by_face_without_repo_unknown(self) -> None:
        out = await PersonService().search_by_face(_vec(0))
        assert out["known"] is False and out["person_id"] is None


class TestKnowledgeService:
    async def test_upsert_and_search_entity(self) -> None:
        svc = KnowledgeService()
        name = _name("Tokopedia")
        await svc.upsert_entity(name=name, category="Organization")
        hits = await svc.search_entity(name[: len("Tokopedia") + 3])
        assert any(h["name"] == name for h in hits)

    async def test_add_relation_and_relationships(self) -> None:
        svc = KnowledgeService()
        pid = _name("pid")
        await PersonService().register_person(name=_name("Asep"), person_id=pid)
        comp = _name("Tokopedia")
        await svc.add_relation(
            person_id=pid, name=comp, category="Organization", relationship="WORKS_AT"
        )
        rel = await svc.entity_relationships(comp)
        assert any(e["type"] == "WORKS_AT" for e in rel["edges"])

    async def test_preferences(self) -> None:
        svc = KnowledgeService()
        pid = _name("pid")
        await PersonService().register_person(name=_name("Asep"), person_id=pid)
        await svc.add_relation(person_id=pid, name="sushi", category="Food", relationship="LIKES")
        prefs = await svc.preferences(pid)
        assert any(p["name"] == "sushi" and p["likes"] for p in prefs)


class TestMemoryService:
    async def test_session_message_history(self) -> None:
        svc = MemoryService()
        sid = await svc.start_session(summary="meet Asep")
        await svc.add_message(session_id=UUID(sid), role="user", content="apa ini?")
        hist = await svc.conversation_history(UUID(sid))
        assert len(hist) == 1 and hist[0]["content"] == "apa ini?" and hist[0]["role"] == "user"

        recent = await svc.recent_memories()
        assert any(r["session_id"] == sid and r["summary"] == "meet Asep" for r in recent)

    async def test_add_facts(self) -> None:
        svc = MemoryService()
        sid = await svc.start_session()
        n = await svc.add_facts(
            facts=["Asep suka kopi", "Asep kerja di Tokopedia"],
            session_id=UUID(sid),
            confidence=0.9,
        )
        assert n == 2
        assert await svc.add_facts(facts=[]) == 0  # empty → no DB round-trip

    async def test_transcripts(self) -> None:
        svc = MemoryService()
        sid = await svc.start_session()
        sm = get_sessionmaker()
        async with sm() as db:
            await TranscriptRepo().add(db, session_id=UUID(sid), text="apa ini?", is_final=True)
        ts = await svc.transcripts(UUID(sid))
        assert len(ts) == 1 and ts[0]["text"] == "apa ini?" and ts[0]["is_final"] is True


class TestReminderService:
    async def test_create_search_today_and_complete(self) -> None:
        svc = ReminderService()
        title = _name("obat")
        due = datetime.now(UTC) + timedelta(hours=1)
        r = await svc.create(title=title, due_at=due, note="sesudah makan")
        assert r["completed"] is False and r["note"] == "sesudah makan"

        found = await svc.search(title[: len("obat")])
        assert any(x["title"] == title for x in found)

        today = await svc.today(now=due)
        assert any(x["title"] == title for x in today)

        await svc.update(UUID(r["reminder_id"]), completed=True)
        after = await svc.today(now=due)
        assert all(x["title"] != title for x in after)  # completed dropped from today

    async def test_upcoming_excludes_past(self) -> None:
        svc = ReminderService()
        title = _name("past")
        await svc.create(title=title, due_at=datetime.now(UTC) - timedelta(hours=2))
        up = await svc.upcoming(after=datetime.now(UTC))
        assert all(x["title"] != title for x in up)

    async def test_delete(self) -> None:
        svc = ReminderService()
        r = await svc.create(title=_name("del"), due_at=datetime.now(UTC) + timedelta(hours=1))
        assert await svc.delete(UUID(r["reminder_id"])) is True
        assert await svc.delete(UUID(r["reminder_id"])) is False


class TestEventService:
    async def test_create_upcoming_search(self) -> None:
        svc = EventService()
        title = _name("kontrol")
        starts = datetime.now(UTC) + timedelta(days=1)
        ev = await svc.create(title=title, starts_at=starts, description="cek", location="rs")
        assert ev["location"] == "rs"

        up = await svc.upcoming(after=datetime.now(UTC))
        assert any(e["title"] == title for e in up)

        hits = await svc.search(title[: len("kontrol")])
        assert any(e["title"] == title for e in hits)

    async def test_delete(self) -> None:
        svc = EventService()
        ev = await svc.create(title=_name("del"), starts_at=datetime.now(UTC) + timedelta(days=1))
        await svc.delete(UUID(ev["event_id"]))
        up = await svc.upcoming(after=datetime.now(UTC))
        assert all(e["title"] != ev["title"] for e in up)


class TestShoppingService:
    async def test_add_list_check_remove(self) -> None:
        svc = ShoppingService()
        name = _name("susu")
        item = await svc.add(name, quantity="2")
        assert item["checked"] is False and item["quantity"] == "2"

        listed = await svc.list_items()
        assert any(i["name"] == name for i in listed)

        checked = await svc.check(name, checked=True)
        assert checked["checked"] is True
        listed = await svc.list_items()
        assert next(i for i in listed if i["name"] == name)["checked"] is True

        assert await svc.remove(name) is True
        assert await svc.remove(name) is False
        assert all(i["name"] != name for i in await svc.list_items())

    async def test_check_missing(self) -> None:
        svc = ShoppingService()
        assert await svc.check(_name("none")) is None


class TestFaceService:
    def test_register_lookup_known(self) -> None:
        svc = FaceService(FaceRepository(FaceIndex(512)))
        v = _vec(0)
        svc.register(v, "person-A")
        out = svc.lookup(v)  # cosine 1.0
        assert out["known"] is True and out["person_id"] == "person-A"
        assert svc.size == 1

    def test_lookup_orthogonal_unknown(self) -> None:
        svc = FaceService(FaceRepository(FaceIndex(512)))
        svc.register(_vec(0), "A")
        out = svc.lookup(_vec(1))  # orthogonal → cosine 0.0 < 0.60
        assert out["known"] is False and out["possible"] is False
        assert out["person_id"] is None

    def test_lookup_midway_possible(self) -> None:
        svc = FaceService(FaceRepository(FaceIndex(512)))
        svc.register(_vec(0), "A")
        mid = (_vec(0) + _vec(1)).astype(np.float32)
        mid /= np.linalg.norm(mid)  # 45° → cosine ≈ 0.707 ∈ [0.60, 0.80)
        out = svc.lookup(mid)
        # possible still identifies the best candidate person, just below known threshold
        assert out["possible"] is True and out["known"] is False
        assert out["person_id"] == "A"

    def test_save_load_roundtrip(self, tmp_path) -> None:
        repo = FaceRepository(FaceIndex(512))
        repo.register(_vec(0), "A")
        repo.register(_vec(1), "B")
        path = str(tmp_path / "faces.faiss")
        repo.save(path)

        loaded = FaceRepository.load(path)
        assert loaded.size == 2
        assert loaded.lookup(_vec(0)).person_id == "A"
        assert loaded.lookup(_vec(1)).person_id == "B"


class TestPersonFaceIntegration:
    """Person + face end-to-end: Neo4j profile linked to a FAISS vector."""

    async def test_register_person_then_face_identifies(self) -> None:
        face_repo = FaceRepository(FaceIndex(512))
        svc = PersonService(face_repo=face_repo)
        pid, name = _name("pid"), _name("Asep")
        await svc.register_person(name=name, person_id=pid)
        await svc.register_face(_vec(0), pid)
        out = await svc.search_by_face(_vec(0))
        assert out["known"] is True
        assert out["person_id"] == pid
        assert out["name"] == name
