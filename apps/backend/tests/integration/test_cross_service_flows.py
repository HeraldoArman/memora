"""Integration tests — cross-service flows + bug regressions against real stores.

Marked `integration`: requires live Postgres + Neo4j + FAISS (`bun run db:start`).
Postgres is truncated before each test (conftest); Neo4j is left intact and tests
use unique person_ids/names so they never collide across runs.

These exercise multi-step, multi-service flows that unit tests (with mocked stores)
can't catch — the kind of thing that breaks in production when a service reads what
another wrote, across Postgres + Neo4j + FAISS boundaries.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import numpy as np
import pytest
from vector.index import FaceIndex
from vector.repository import FaceRepository

from postgres.repositories import FactRepo, SystemRepo, TranscriptRepo
from postgres.session import get_sessionmaker
from services import (
    EventService,
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
    """Deterministic 512-d unit vector along `axis` — mutually orthogonal."""
    v = np.zeros(512, dtype=np.float32)
    v[axis] = 1.0
    return v


# ---------------------------------------------------------------------------
# Bug regression: UPSERT_PERSON dropped a caller's person_id on a name match
# ---------------------------------------------------------------------------


class TestPersonUpsertBugRegression:
    """The original bug: re-registering an existing name with a NEW person_id
    silently kept the old id (MERGE on name, ON CREATE SET person_id never fired).
    get_person(new_id) returned None and face vectors detached from profiles.

    Fix: MERGE on person_id when provided (caller-authoritative); MERGE on name
    only when no id is given (consolidator dedupe-by-name path).
    """

    async def test_re_register_same_name_new_id_updates_identity(self) -> None:
        """Re-registering an existing name with a fresh person_id must make that
        id resolvable — the bug returned the OLD id, so get_person(new_id) was None."""
        svc = PersonService()
        name = _name("Asep")
        old_pid, new_pid = _name("old"), _name("new")
        await svc.register_person(name=name, person_id=old_pid)
        await svc.register_person(name=name, person_id=new_pid)
        # new id must resolve to the same name
        got = await svc.get_person(new_pid)
        assert got is not None and got["name"] == name
        # old id is a separate node now (merge on person_id, not name) — both exist
        assert (await svc.get_person(old_pid))["name"] == name

    async def test_register_then_face_enroll_resolves_full_identity(self) -> None:
        """End-to-end identity flow: register person → enroll face → lookup by face
        → resolve profile. This is the exact path the bug broke (register_face stored
        the caller's id, but get_person couldn't find it)."""
        face_repo = FaceRepository(FaceIndex(512))
        svc = PersonService(face_repo=face_repo)
        pid, name = _name("pid"), _name("Asep")
        await svc.register_person(name=name, person_id=pid)
        await svc.register_face(_vec(0), pid)
        out = await svc.search_by_face(_vec(0))
        assert out["known"] is True
        assert out["person_id"] == pid
        assert out["name"] == name

    async def test_dedupe_by_name_when_no_id(self) -> None:
        """Consolidator path (no person_id): re-mentioning a name reuses the same
        node — no duplicate Person nodes fragmenting facts."""
        svc = PersonService()
        name = _name("Dewi")
        first = await svc.register_person(name=name)
        second = await svc.register_person(name=name)
        assert first["person_id"] == second["person_id"], "dedupe-by-name lost"

    async def test_explicit_id_overrides_existing_name_node(self) -> None:
        """A name-only register creates node A; a later register with an explicit id
        for the same name creates node B (caller wants its own id). Both resolve."""
        svc = PersonService()
        name = _name("Sari")
        a = await svc.register_person(name=name)
        explicit = _name("explicit")
        b = await svc.register_person(name=name, person_id=explicit)
        assert a["person_id"] != explicit
        assert b["person_id"] == explicit
        assert (await svc.get_person(a["person_id"]))["name"] == name
        assert (await svc.get_person(explicit))["name"] == name


# ---------------------------------------------------------------------------
# Person + Knowledge graph flows
# ---------------------------------------------------------------------------


class TestPersonKnowledgeGraphFlow:
    async def test_person_works_at_then_preferences(self) -> None:
        """Register person → add WORKS_AT org + LIKES food → preferences + relationships resolve."""
        person = PersonService()
        kg = KnowledgeService()
        pid = _name("pid")
        await person.register_person(name=_name("Asep"), person_id=pid)
        org = _name("Tokopedia")
        food = _name("sushi")
        await kg.add_relation(
            person_id=pid, name=org, category="Organization", relationship="WORKS_AT"
        )
        await kg.add_relation(person_id=pid, name=food, category="Food", relationship="LIKES")

        rels = await kg.entity_relationships(org)
        assert any(e["type"] == "WORKS_AT" for e in rels["edges"])

        prefs = await kg.preferences(pid)
        assert any(p["name"] == food and p["likes"] for p in prefs)

    async def test_update_person_notes_persist(self) -> None:
        svc = PersonService()
        pid = _name("pid")
        await svc.register_person(name=_name("Asep"), person_id=pid)
        updated = await svc.update_person(person_id=pid, notes="suka kopi tubruk")
        assert updated["notes"] == "suka kopi tubruk"
        assert (await svc.get_person(pid))["notes"] == "suka kopi tubruk"

    async def test_related_people_bidirectional(self) -> None:
        """KNOWS edge from A→B; related_people(A) finds B."""
        svc = PersonService()
        a, b = _name("a"), _name("b")
        await svc.register_person(name=_name("Ana"), person_id=a)
        await svc.register_person(name=_name("Budi"), person_id=b)
        await svc.kg_repo.add_relation(
            person_id=a, name=_name("Budi"), category="Person", relationship="KNOWS"
        )
        related = await svc.related_people(a)
        # Budi linked via KNOWS edge — find by the relation we added
        assert len(related) >= 1


# ---------------------------------------------------------------------------
# Memory service: session → messages → facts → transcripts → history
# ---------------------------------------------------------------------------


class TestMemoryServiceFlow:
    async def test_session_lifecycle_messages_facts_transcripts(self) -> None:
        """Full episodic flow: start session → add messages → add facts → transcripts
        → recent_memories reflects the session, history ordered, facts persisted."""
        mem = MemoryService()
        sid = await mem.start_session(summary="meet Asep di apotek")
        sid_uuid = UUID(sid)

        await mem.add_message(session_id=sid_uuid, role="user", content="Halo Asep!")
        await mem.add_message(session_id=sid_uuid, role="assistant", content="Halo!")

        n = await mem.add_facts(
            facts=["Asep suka kopi", "Asep kerja di apotek"],
            session_id=sid_uuid,
            confidence=0.9,
        )
        assert n == 2

        sm = get_sessionmaker()
        async with sm() as db:
            await TranscriptRepo().add(db, session_id=sid_uuid, text="Halo Asep", is_final=True)
            await TranscriptRepo().add(db, session_id=sid_uuid, text="apa ini", is_final=False)

        hist = await mem.conversation_history(sid_uuid)
        assert len(hist) == 2
        assert [m["role"] for m in hist] == ["user", "assistant"]

        ts = await mem.transcripts(sid_uuid)
        assert len(ts) == 2
        assert ts[0]["is_final"] is True and ts[1]["is_final"] is False

        recent = await mem.recent_memories()
        assert any(r["session_id"] == sid and r["summary"] == "meet Asep di apotek" for r in recent)

    async def test_add_facts_per_fact_confidence_alignment(self) -> None:
        """confidences list (per-fact) must align with facts; mismatched length raises."""
        mem = MemoryService()
        sid = await mem.start_session()
        # per-fact confidences (first-person boost path)
        n = await mem.add_facts(
            facts=["I'm Asep", "Asep works at Tokopedia"],
            session_id=UUID(sid),
            confidences=[0.95, 0.85],
        )
        assert n == 2
        # mismatched length → ValueError from the repo
        with pytest.raises(ValueError, match="align"):
            await mem.add_facts(facts=["a", "b"], confidences=[0.9])

    async def test_add_facts_empty_no_op(self) -> None:
        mem = MemoryService()
        assert await mem.add_facts(facts=[]) == 0

    async def test_history_limit_respected(self) -> None:
        mem = MemoryService()
        sid = UUID(await mem.start_session())
        for i in range(5):
            await mem.add_message(session_id=sid, role="user", content=f"msg-{i}")
        hist = await mem.conversation_history(sid, limit=3)
        assert len(hist) == 3
        assert [m["content"] for m in hist] == ["msg-0", "msg-1", "msg-2"]


# ---------------------------------------------------------------------------
# Reminder service: timezone window + boundary edges
# ---------------------------------------------------------------------------


class TestReminderTimezoneEdges:
    """The local-day window (Asia/Jakarta, UTC+7) is the trickiest reminder logic —
    a UTC midnight window missed every reminder due local 00:00–06:59. These pin
    the boundary behavior so a refactor can't silently regress it."""

    async def test_reminder_due_local_today_midnight_utc(self) -> None:
        """A reminder due at 00:00 local (17:00 UTC prev day) is 'today' in local terms."""
        svc = ReminderService()
        # 00:00 Asia/Jakarta = 17:00 UTC previous day
        local_midnight_utc = datetime(2026, 8, 10, 17, 0, tzinfo=UTC)
        title = _name("pagi")
        await svc.create(title=title, due_at=local_midnight_utc)
        # 'today' computed at 09:00 local (02:00 UTC same day)
        now = datetime(2026, 8, 11, 2, 0, tzinfo=UTC)
        today = await svc.today(now=now)
        assert any(x["title"] == title for x in today)

    async def test_completed_excluded_from_today(self) -> None:
        svc = ReminderService()
        due = datetime.now(UTC) + timedelta(hours=1)
        title = _name("obat")
        await svc.create(title=title, due_at=due)
        rid = (await svc.search(title))[0]["reminder_id"]
        await svc.update(UUID(rid), completed=True)
        today = await svc.today(now=due)
        assert all(x["title"] != title for x in today)

    async def test_upcoming_orders_by_due_at(self) -> None:
        svc = ReminderService()
        t1, t2 = _name("a"), _name("b")
        await svc.create(title=t2, due_at=datetime.now(UTC) + timedelta(hours=5))
        await svc.create(title=t1, due_at=datetime.now(UTC) + timedelta(hours=1))
        up = await svc.upcoming(after=datetime.now(UTC))
        assert [r["title"] for r in up] == [t1, t2]

    async def test_update_missing_returns_none(self) -> None:
        assert await ReminderService().update(uuid4(), completed=True) is None

    async def test_search_matches_note_too(self) -> None:
        """search() matches title OR note (ilike)."""
        svc = ReminderService()
        note = _name("catatan")
        await svc.create(title=_name("x"), due_at=datetime.now(UTC) + timedelta(hours=1), note=note)
        hits = await svc.search(note[:8])
        assert any(h["note"] == note for h in hits)


# ---------------------------------------------------------------------------
# Shopping service: default-list idempotency + case-insensitive match
# ---------------------------------------------------------------------------


class TestShoppingServiceFlow:
    async def test_default_list_created_once(self) -> None:
        """get_or_create_default is idempotent — two add() calls share one list."""
        svc = ShoppingService()
        await svc.add(_name("susu"))
        await svc.add(_name("kopi"))
        listed = await svc.list_items()
        assert len(listed) == 2

    async def test_check_case_insensitive(self) -> None:
        """find_item matches case-insensitively (func.lower), not substring."""
        svc = ShoppingService()
        name = _name("Susu")
        await svc.add(name)
        assert await svc.check(name.lower()) is not None
        listed = await svc.list_items()
        assert next(i for i in listed if i["name"] == name)["checked"] is True

    async def test_check_no_wildcard_match(self) -> None:
        """A caller's %/_ must not pattern-match other rows (the old ilike bug)."""
        svc = ShoppingService()
        await svc.add("susu sapi")
        await svc.add("susu kambing")
        # '%' would match both under ilike; exact case-insensitive match finds neither
        assert await svc.check("%") is None
        assert await svc.check("susu%") is None

    async def test_remove_idempotent(self) -> None:
        svc = ShoppingService()
        name = _name("telur")
        await svc.add(name)
        assert await svc.remove(name) is True
        assert await svc.remove(name) is False  # already gone


# ---------------------------------------------------------------------------
# Event service: ordering + search + delete
# ---------------------------------------------------------------------------


class TestEventServiceFlow:
    async def test_upcoming_excludes_past(self) -> None:
        svc = EventService()
        await svc.create(title=_name("past"), starts_at=datetime.now(UTC) - timedelta(days=1))
        up = await svc.upcoming(after=datetime.now(UTC))
        assert all(e["title"] != "past" for e in up)

    async def test_upcoming_orders_by_starts_at(self) -> None:
        svc = EventService()
        t1, t2 = _name("a"), _name("b")
        await svc.create(title=t2, starts_at=datetime.now(UTC) + timedelta(days=5))
        await svc.create(title=t1, starts_at=datetime.now(UTC) + timedelta(days=1))
        up = await svc.upcoming(after=datetime.now(UTC))
        assert [e["title"] for e in up] == [t1, t2]

    async def test_delete_removes_from_upcoming(self) -> None:
        svc = EventService()
        ev = await svc.create(title=_name("del"), starts_at=datetime.now(UTC) + timedelta(days=1))
        await svc.delete(UUID(ev["event_id"]))
        up = await svc.upcoming(after=datetime.now(UTC))
        assert all(e["title"] != ev["title"] for e in up)

    async def test_create_with_ends_at(self) -> None:
        svc = EventService()
        start = datetime.now(UTC) + timedelta(days=1)
        end = start + timedelta(hours=2)
        ev = await svc.create(title=_name("e"), starts_at=start, ends_at=end, location="rs")
        assert ev["ends_at"] is not None and ev["location"] == "rs"


# ---------------------------------------------------------------------------
# System repo (logs + settings) — previously untested at integration level
# ---------------------------------------------------------------------------


class TestSystemRepo:
    async def test_setting_set_get_roundtrip(self) -> None:
        sm = get_sessionmaker()
        repo = SystemRepo()
        key = _name("key")
        async with sm() as db:
            await repo.set_setting(db, key=key, value="v1")
            assert await repo.get_setting(db, key=key) == "v1"
            await repo.set_setting(db, key=key, value="v2")  # update existing
            assert await repo.get_setting(db, key=key) == "v2"

    async def test_get_missing_setting_returns_none(self) -> None:
        sm = get_sessionmaker()
        async with sm() as db:
            assert await SystemRepo().get_setting(db, key=_name("nope")) is None

    async def test_log_persists(self) -> None:
        sm = get_sessionmaker()
        repo = SystemRepo()
        msg = _name("msg")
        async with sm() as db:
            entry = await repo.log(db, message=msg, level="WARN", source="test")
            assert entry.message == msg and entry.level == "WARN" and entry.source == "test"


# ---------------------------------------------------------------------------
# Pipeline end-to-end through real stores (mock extractor → real consolidator)
# ---------------------------------------------------------------------------


class TestPipelineConsolidatorIntegration:
    """The consolidator writes through real services into Postgres + Neo4j. A mock
    extractor feeds deterministic structured knowledge; we verify the graph + episodic
    records land in the real stores (the wiring unit tests mock). Conversation messages
    are persisted separately by the LiveKit gateway at turn boundaries."""

    async def test_consolidate_writes_graph_and_facts(self) -> None:

        # Names must survive resolve_name/normalize unchanged. normalize() title-cases
        # then lowercases mixed-case tokens, so use simple Title-cased single words.
        # _name() appends a hex suffix that .title() mangles — use a random alpha suffix.
        import random
        import string

        suf = "".join(random.choices(string.ascii_lowercase, k=6))
        person_canon = f"Asep{suf}".title()  # Asepabcdef
        org_name = f"Tokopedia{suf}".title()
        food_name = f"Sushi{suf}".title()
        # normalize lowercases the tail — these are what land in the graph
        from extraction.normalizer import normalize

        org_canon = normalize(org_name)
        food_canon = normalize(food_name)

        class _MockExtractor:
            async def extract(self, content: str) -> dict:
                return {
                    "entities": [
                        {
                            "name": person_canon,
                            "category": "Person",
                            "canonical_name": person_canon,
                        },
                        {"name": org_name, "category": "Organization", "canonical_name": org_name},
                        {"name": food_name, "category": "Food", "canonical_name": food_name},
                    ],
                    "relationships": [
                        {"subject": person_canon, "relationship": "WORKS_AT", "object": org_name},
                        {"subject": person_canon, "relationship": "LIKES", "object": food_name},
                    ],
                    "facts": [f"{person_canon} works at {org_name}"],
                    "confidence": 0.95,
                }

        from pipeline.runner import PipelineRunner

        mem = MemoryService()
        sid = await mem.start_session(summary="pipeline e2e")
        runner = PipelineRunner(extractor=_MockExtractor())
        summary = await runner.run(
            f"I'm {person_canon}, I work at {org_name}, I like {food_name}",
            session_id=sid,
        )
        assert summary["action"] == "create"
        assert summary["entities"] == 3
        assert summary["relationships"] == 2

        # Extracted fact persisted. The LiveKit gateway owns episodic message persistence.
        async with get_sessionmaker()() as db:
            facts = await FactRepo().list_recent(db, session_id=UUID(sid), limit=10)
        assert any(person_canon in fact.fact for fact in facts)

        # Graph: person reachable by the id the consolidator registered
        pid = summary["person_ids"][person_canon]
        person_svc = PersonService()
        profile = await person_svc.get_person(pid)
        assert profile is not None
        rel_types = {
            (r["type"], r["target"]) for r in profile.get("relationships", []) if r["type"]
        }
        assert ("WORKS_AT", org_canon) in rel_types, rel_types
        assert any(t == "LIKES" and tgt == food_canon for t, tgt in rel_types), rel_types

    async def test_consolidate_reject_low_confidence_no_writes(self) -> None:

        class _MockExtractor:
            async def extract(self, content: str) -> dict:
                return {"entities": [], "relationships": [], "confidence": 0.1}

        from pipeline.runner import PipelineRunner

        mem = MemoryService()
        sid = await mem.start_session()
        runner = PipelineRunner(extractor=_MockExtractor())
        # Substantive enough to pass the filter (>= 6 chars, not trivial), low confidence
        # → consolidator rejects → no episodic message.
        summary = await runner.run("sesuatu yang tidak jelas", session_id=sid)
        assert summary["action"] == "reject"
        assert await mem.conversation_history(UUID(sid)) == []

    async def test_consolidate_unknown_relationship_dropped(self) -> None:
        """An LLM relationship type outside RelationshipType must be dropped before
        it reaches Cypher (it's f-string'd into the edge label — injection guard)."""

        person_name = _name("Asep")
        org_name = _name("EvilCorp")

        class _MockExtractor:
            async def extract(self, content: str) -> dict:
                return {
                    "entities": [
                        {"name": person_name, "category": "Person"},
                        {"name": org_name, "category": "Organization"},
                    ],
                    "relationships": [
                        # valid
                        {"subject": person_name, "relationship": "WORKS_AT", "object": org_name},
                        # invalid — must be dropped, not injected into Cypher
                        {
                            "subject": person_name,
                            "relationship": "HACKS`; DROP",
                            "object": org_name,
                        },
                    ],
                    "confidence": 0.9,
                }

        from pipeline.runner import PipelineRunner

        sid = await MemoryService().start_session()
        runner = PipelineRunner(extractor=_MockExtractor())
        summary = await runner.run(f"{person_name} hacks {org_name}", session_id=sid)
        assert summary["relationships"] == 1  # only WORKS_AT persisted


# ---------------------------------------------------------------------------
# Face re-recognition: possible match → confirm → enroll improves identity
# ---------------------------------------------------------------------------


class TestFaceReRecognitionFlow:
    """The core plot-hole fix: user meets someone they know but FAISS doesn't
    recognise them (bad angle / lighting / different appearance). The possible
    match (0.60-0.80) should surface the candidate name so the agent can ask
    'Is this X?' — and on confirmation, re-enrolling the face under the existing
    person_id strengthens future recognition.

    Also: user meets someone with NO face match at all. They say the name in
    conversation. The agent should search_person first (to avoid duplicates),
    then register_face to link the unknown embedding to the existing/new node.
    """

    async def test_possible_match_surfaces_candidate_name(self) -> None:
        """Enroll one embedding → lookup with a partially similar embedding
        → should return is_possible=True with the candidate name."""
        face_repo = FaceRepository(FaceIndex(512))
        svc = PersonService(face_repo=face_repo)
        pid, name = _name("pid"), _name("Asep")
        await svc.register_person(name=name, person_id=pid)
        await svc.register_face(_vec(0), pid)
        # 0.42 cosine similarity — above possible (0.35), below known (0.50)
        # After L2 normalization the first component must be 0.42, so the second
        # is sqrt(1 - 0.42^2) = sqrt(0.8236) ≈ 0.9075.
        partial = np.zeros(512, dtype=np.float32)
        partial[0] = 0.42
        partial[1] = float(np.sqrt(1 - 0.42**2))
        out = await svc.search_by_face(partial)
        assert out["known"] is False
        assert out["possible"] is True
        assert out["person_id"] == pid
        assert out["name"] == name

    async def test_re_enroll_after_possible_match_strengthens_identity(self) -> None:
        """After a possible match is confirmed and the face is re-enrolled under
        the same person_id, a subsequent lookup with the same vector should
        register as a strong (known) match — two vectors in the index."""
        face_repo = FaceRepository(FaceIndex(512))
        svc = PersonService(face_repo=face_repo)
        pid, name = _name("pid"), _name("Budi")
        await svc.register_person(name=name, person_id=pid)
        # Original enrollment
        await svc.register_face(_vec(0), pid)
        # Agent confirmed possible match → re-enroll the new angle
        partial = np.zeros(512, dtype=np.float32)
        partial[0] = 0.42
        partial[1] = float(np.sqrt(1 - 0.42**2))
        await svc.register_face(partial, pid)
        # Now lookup with the partial vector → should hit the exact enrolled copy
        out = await svc.search_by_face(partial)
        assert out["known"] is True, "re-enrollment should make this a known match"
        assert out["person_id"] == pid
        assert out["name"] == name

    async def test_no_match_at_all_returns_unknown(self) -> None:
        """Completely unknown face (orthogonal vector) returns no person_id."""
        face_repo = FaceRepository(FaceIndex(512))
        svc = PersonService(face_repo=face_repo)
        pid, name = _name("pid"), _name("Caca")
        await svc.register_person(name=name, person_id=pid)
        await svc.register_face(_vec(0), pid)
        out = await svc.search_by_face(_vec(5))  # orthogonal
        assert out["known"] is False
        assert out["possible"] is False
        assert out["person_id"] is None

    async def test_search_person_before_register_avoids_duplicate(self) -> None:
        """The name-in-conversation flow: agent should search_person first.
        If the person exists, register_face under the existing person_id —
        NOT register_person (which would create a duplicate node)."""
        svc = PersonService()
        name = _name("Dini")
        # Person already exists from a prior conversation
        existing = await svc.register_person(name=name)
        existing_pid = existing["person_id"]
        # Agent calls search_person → finds the existing node
        hits = await svc.search_by_name(name)
        person_hits = [h for h in hits if h.get("name") == name]
        assert len(person_hits) >= 1
        # Agent should use the existing person_id, not register a new one
        # (verify that re-registering by name without id dedupes)
        deduped = await svc.register_person(name=name)
        assert deduped["person_id"] == existing_pid

    async def test_full_unknown_face_to_enrolled_flow(self) -> None:
        """End-to-end: face not in FAISS → user says name → agent searches →
        not found → register_person → register_face → next lookup is known."""
        face_repo = FaceRepository(FaceIndex(512))
        svc = PersonService(face_repo=face_repo)
        name = _name("Eka")
        # 1. Face not in FAISS
        out = await svc.search_by_face(_vec(2))
        assert out["known"] is False and out["possible"] is False
        # 2. Agent searches by name — not found
        hits = await svc.search_by_name(name)
        assert not any(h.get("name") == name for h in hits)
        # 3. Agent registers person
        node = await svc.register_person(name=name)
        pid = node["person_id"]
        # 4. Agent links the face embedding
        await svc.register_face(_vec(2), pid)
        # 5. Next lookup → known
        out2 = await svc.search_by_face(_vec(2))
        assert out2["known"] is True
        assert out2["person_id"] == pid
        assert out2["name"] == name


# ---------------------------------------------------------------------------
# 24/7 glasses: orphan facts + retroactive linking + time windowing
# ---------------------------------------------------------------------------


class TestOrphanFactsAndRetroactiveLinking:
    """The 24/7 glasses plot hole: user meets someone they know but the glasses
    don't recognise them. They talk (facts extracted, no person identified → orphaned).
    Later the person is identified via register_person. The orphan facts from the
    recent conversation should be retroactively linked to the new person.

    Time-windowed (last 10 min) so 24/7 sessions don't mix up facts from different
    conversation partners throughout the day.
    """

    async def _get_facts(self, session_id, limit=10):
        """Helper: list facts for a session using a proper async context."""
        from uuid import UUID

        sm = get_sessionmaker()
        async with sm() as db:
            return await FactRepo().list_recent(db, session_id=UUID(session_id), limit=limit)

    async def test_orphan_facts_have_no_person_id(self) -> None:
        """Facts extracted without a person identified are orphaned (person_id=NULL)."""
        mem = MemoryService()
        sid = await mem.start_session()
        from uuid import UUID

        await mem.add_facts(
            facts=["sushi is delicious", "likes coffee"],
            session_id=UUID(sid),
        )
        facts = await self._get_facts(sid)
        for f in facts:
            assert f.person_id is None, f"fact should be orphaned: {f.fact}"

    async def test_facts_tagged_when_single_person_identified(self) -> None:
        """When the consolidator sees exactly one person, facts are tagged with their person_id."""
        mem = MemoryService()
        sid = await mem.start_session()
        from uuid import UUID

        pid = _name("pid")
        await mem.add_facts(
            facts=["Asep suka sushi"],
            session_id=UUID(sid),
            person_id=pid,
        )
        facts = await self._get_facts(sid)
        assert len(facts) == 1
        assert facts[0].person_id == pid

    async def test_retroactive_linking_within_time_window(self) -> None:
        """Orphan facts from the current conversation are linked to the person
        when register_person is called within the 10-minute window."""
        mem = MemoryService()
        sid = await mem.start_session()
        from uuid import UUID

        # Orphan facts (no person_id)
        await mem.add_facts(facts=["suka sushi"], session_id=UUID(sid))
        await mem.add_facts(facts=["kerja di apotek"], session_id=UUID(sid))

        # Person identified later
        pid = _name("pid")
        linked = await mem.link_facts_to_person(session_id=UUID(sid), person_id=pid)
        assert linked == 2, f"expected 2 orphan facts linked, got {linked}"

        # Verify they're linked
        facts = await self._get_facts(sid)
        for f in facts:
            assert f.person_id == pid, f"fact not linked: {f.fact}"

    async def test_old_facts_not_linked_outside_time_window(self) -> None:
        """Facts older than 10 minutes are NOT linked — they belong to a prior conversation."""
        mem = MemoryService()
        sid = await mem.start_session()
        from datetime import UTC, datetime, timedelta
        from uuid import UUID

        from postgres.models import MemoryFact

        # Insert an orphan fact with an old timestamp
        sm = get_sessionmaker()
        async with sm() as db:
            old_fact = MemoryFact(
                session_id=UUID(sid),
                person_id=None,
                fact="old conversation fact",
                created_at=datetime.now(UTC) - timedelta(minutes=30),
            )
            db.add(old_fact)
            await db.commit()

        # Also insert a recent orphan fact
        await mem.add_facts(facts=["recent fact"], session_id=UUID(sid))

        # Link — should only get the recent one, not the old one
        pid = _name("pid")
        linked = await mem.link_facts_to_person(session_id=UUID(sid), person_id=pid)
        assert linked == 1, (
            f"expected 1 recent fact linked (old one should be skipped), got {linked}"
        )

    async def test_already_linked_facts_not_relinked(self) -> None:
        """Facts already linked to a person should not be re-linked to a new person."""
        mem = MemoryService()
        sid = await mem.start_session()
        from uuid import UUID

        old_pid = _name("old")
        new_pid = _name("new")

        # Fact already linked to old_pid
        await mem.add_facts(facts=["already linked"], session_id=UUID(sid), person_id=old_pid)
        # Orphan fact
        await mem.add_facts(facts=["orphan"], session_id=UUID(sid))

        linked = await mem.link_facts_to_person(session_id=UUID(sid), person_id=new_pid)
        assert linked == 1, f"expected only 1 orphan fact linked, got {linked}"

        # Verify the old fact still points to old_pid
        facts = await self._get_facts(sid)
        for f in facts:
            if f.fact == "already linked":
                assert f.person_id == old_pid, "already-linked fact should not be re-linked"

    async def test_full_247_scenario_orphan_then_identify(self) -> None:
        """Full scenario: 24/7 glasses, unknown person, talk about sushi → orphan fact
        → person identified via register_person → retroactive link → fact is now theirs."""
        from uuid import UUID

        mem = MemoryService()
        sid = await mem.start_session()

        # 1. Conversation happens, no name spoken → orphan fact
        await mem.add_facts(facts=["suka sushi"], session_id=UUID(sid))

        # 2. Later, person is identified (agent calls register_person, which links)
        pid = _name("pid")
        await mem.link_facts_to_person(session_id=UUID(sid), person_id=pid)

        # 3. Fact is now linked to this person
        facts = await self._get_facts(sid)
        assert len(facts) == 1
        assert facts[0].person_id == pid
        assert facts[0].fact == "suka sushi"
