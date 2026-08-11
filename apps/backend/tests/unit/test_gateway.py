"""Unit tests — gateway: RoomSession lifecycle, track_handler face lookup + audio shim,
entrypoint _init_stores graceful degradation, WorkerOptions wiring.

No LiveKit connection, no DB: face lookup uses a real in-memory FaceRepository; stores
are patched to fail. The ReasoningAgent is stubbed in the create() test.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
from vector.index import FaceIndex
from vector.repository import FaceRepository

from gateway.livekit.entrypoint import _init_stores, entrypoint
from gateway.livekit.track_handler import _AudioShim, _lookup_face
from gateway.session import RoomSession
from perception.observation.engine import ObservationEngine
from perception.observation.working_memory import WorkingMemory
from tools import ToolContext


def _face_repo() -> FaceRepository:
    repo = FaceRepository(FaceIndex(dim=8), known_threshold=0.80, possible_threshold=0.60)
    v = np.zeros(8, dtype=np.float32)
    v[0] = 1.0
    repo.register(v, "person-1")
    return repo


def _patch_face_repo(monkeypatch, repo: FaceRepository | None = None) -> FaceRepository:
    """Patch FaceRepository.from_db to return an in-memory repo (no DB in unit tests)."""
    repo = repo or _face_repo()
    monkeypatch.setattr(
        "vector.repository.FaceRepository.from_db",
        AsyncMock(return_value=repo),
    )
    return repo


class _FakeAgent:
    """Stands in for ReasoningAgent in RoomSession.create — records construction kwargs."""

    def __init__(self, **kwargs) -> None:
        self.room = kwargs["room"]
        self.ctx = kwargs["tool_ctx"]
        self.on_extract = kwargs["on_extract"]
        self.emit_observation = kwargs["emit_observation"]
        self.started = False

    async def start(self, current=None) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False


class TestRoomSessionCreate:
    async def test_create_wires_collaborators(self, monkeypatch) -> None:
        repo = _patch_face_repo(monkeypatch)
        monkeypatch.setattr("gateway.session.ReasoningAgent", _FakeAgent)
        room = MagicMock()
        session = await RoomSession.create(room)
        assert session.session_id is None  # conversation session is lazy
        assert session.face_repo is repo
        assert session.tool_ctx.face_repo is session.face_repo
        assert session.agent.room is room
        assert session.agent.ctx is session.tool_ctx
        # bound methods compare equal (same func + instance) but aren't `is`-identical
        assert session.agent.emit_observation == session.observation_engine.emit

    async def test_on_extract_lazy_session_and_threading(self, monkeypatch) -> None:
        _patch_face_repo(monkeypatch)
        monkeypatch.setattr("gateway.session.ReasoningAgent", _FakeAgent)
        session = await RoomSession.create(MagicMock())

        runs: list[dict] = []

        async def _fake_run(text, *, session_id=None):
            runs.append({"text": text, "session_id": session_id})
            return {"action": "create"}

        async def _start_session(*, summary=None):
            return "session-abc"

        with (
            patch(
                "services.MemoryService.start_session",
                new=AsyncMock(side_effect=_start_session),
            ),
            patch("pipeline.runner.PipelineRunner.run", new=AsyncMock(side_effect=_fake_run)),
        ):
            await session.agent.on_extract("Halo Asep")
            await session.agent.on_extract("Beli obat lagi")

        assert session.session_id == "session-abc"
        assert runs == [
            {"text": "Halo Asep", "session_id": "session-abc"},
            {"text": "Beli obat lagi", "session_id": "session-abc"},
        ]

    async def test_on_extract_db_down_does_not_raise(self, monkeypatch) -> None:
        _patch_face_repo(monkeypatch)
        monkeypatch.setattr("gateway.session.ReasoningAgent", _FakeAgent)
        session = await RoomSession.create(MagicMock())

        with (
            patch(
                "services.MemoryService.start_session",
                new=AsyncMock(side_effect=RuntimeError("db down")),
            ),
        ):
            await session.agent.on_extract("apa ini")  # must not raise

        assert session.session_id is None


class TestRoomSessionLifecycle:
    def _session(self) -> RoomSession:
        wm = WorkingMemory()
        obs = ObservationEngine(wm)
        ctx = ToolContext()
        agent = MagicMock()
        agent.start = AsyncMock()
        agent.stop = AsyncMock()
        return RoomSession(working_memory=wm, observation_engine=obs, tool_ctx=ctx, agent=agent)

    async def test_start(self) -> None:
        s = self._session()
        s.observation_engine._task = None  # don't actually start the loop
        s.agent.start = AsyncMock()
        with patch.object(s.observation_engine, "start") as mock_start:
            await s.start()
        mock_start.assert_called_once()
        s.agent.start.assert_awaited_once()

    async def test_stop_cancels_tasks_and_stops(self) -> None:
        s = self._session()
        cancelled = []

        class _T:
            def cancel(self):
                cancelled.append(True)

        s.tasks = [_T()]
        s.observation_engine.stop = AsyncMock()
        s.agent.stop = AsyncMock()
        await s.stop()
        assert cancelled == [True]
        s.observation_engine.stop.assert_awaited_once()
        s.agent.stop.assert_awaited_once()

    def test_sync_context(self) -> None:
        from dto.observations import CurrentContext

        s = self._session()
        ctx = CurrentContext(scene="apotek")
        s.working_memory.set(ctx)
        s.sync_context()
        assert s.tool_ctx.current_context is ctx


class TestLookupFace:
    async def test_none_repo(self) -> None:
        assert await _lookup_face(np.zeros(8, dtype=np.float32), None) is None

    async def test_known_resolves_name(self) -> None:
        repo = _face_repo()
        v = np.zeros(8, dtype=np.float32)
        v[0] = 1.0
        with patch("graph.repository.PersonRepo") as mock_repo_cls:
            mock_repo_cls.return_value.get_person = AsyncMock(return_value={"name": "Asep"})
            obs = await _lookup_face(v, repo)
        assert obs is not None
        assert obs.person_id == "person-1"
        assert obs.name == "Asep"
        assert obs.is_known and obs.confidence > 0.99

    async def test_graph_down_keeps_observation(self) -> None:
        repo = _face_repo()
        v = np.zeros(8, dtype=np.float32)
        v[0] = 1.0
        with patch("graph.repository.PersonRepo") as mock_repo_cls:
            mock_repo_cls.return_value.get_person = AsyncMock(
                side_effect=RuntimeError("neo4j down")
            )
            obs = await _lookup_face(v, repo)
        assert obs is not None
        assert obs.person_id == "person-1"
        assert obs.name is None  # degraded, not dropped
        assert obs.is_known

    async def test_unknown_face(self) -> None:
        repo = _face_repo()
        v = np.zeros(8, dtype=np.float32)
        v[0] = 1.0
        unknown = np.zeros(8, dtype=np.float32)
        unknown[1] = 1.0  # orthogonal → unknown
        obs = await _lookup_face(unknown, repo)
        assert obs is not None
        assert obs.person_id is None
        assert not obs.is_known and not obs.is_possible_match

    async def test_possible_match_resolves_name(self) -> None:
        """FAISS possible match (0.60-0.80) resolves the name so fuse() can surface 'Mungkin <name>'."""
        repo = _face_repo()
        v = np.zeros(8, dtype=np.float32)
        v[0] = 1.0
        # Partial match: 0.7 cosine similarity (above 0.60 possible, below 0.80 known)
        # After L2 normalization the first component must be 0.7, so the second
        # is sqrt(1 - 0.7^2) ≈ 0.714.
        partial = np.zeros(8, dtype=np.float32)
        partial[0] = 0.7
        partial[1] = float(np.sqrt(1 - 0.7**2))
        with patch("graph.repository.PersonRepo") as mock_repo_cls:
            mock_repo_cls.return_value.get_person = AsyncMock(return_value={"name": "Asep"})
            obs = await _lookup_face(partial, repo)
        assert obs is not None
        assert obs.person_id == "person-1"
        assert obs.name == "Asep"
        assert not obs.is_known
        assert obs.is_possible_match


class TestAudioShim:
    def _agent(self):
        return SimpleNamespace(calls=[])

    async def test_parses_rate_and_dispatches(self) -> None:
        from google.genai import types

        agent = MagicMock()
        agent.feed_audio = AsyncMock()
        shim = _AudioShim(agent)
        blob = types.Blob(mime_type="audio/pcm;rate=16000", data=b"\x00\x01")
        await shim.send_realtime_input(audio=blob)
        agent.feed_audio.assert_awaited_once_with(b"\x00\x01", sample_rate=16000)

        agent.feed_audio.reset_mock()
        blob2 = types.Blob(mime_type="audio/pcm;rate=8000", data=b"\x04")
        await shim.send_realtime_input(audio=blob2)
        agent.feed_audio.assert_awaited_once_with(b"\x04", sample_rate=8000)

    async def test_no_audio_noop(self) -> None:
        agent = MagicMock()
        agent.feed_audio = AsyncMock()
        await _AudioShim(agent).send_realtime_input(audio=None)
        agent.feed_audio.assert_not_called()


class TestInitStores:
    async def test_stores_ok(self, monkeypatch) -> None:
        init_engine = MagicMock()
        init_driver = AsyncMock()
        monkeypatch.setattr("postgres.session.init_engine", init_engine)
        monkeypatch.setattr("graph.client.init_driver", init_driver)
        await _init_stores()
        init_engine.assert_called_once()
        init_driver.assert_awaited_once()

    async def test_both_down_no_raise(self, monkeypatch) -> None:
        def _boom(*a, **k):
            raise RuntimeError("postgres down")

        async def _boom_async(*a, **k):
            raise RuntimeError("neo4j down")

        monkeypatch.setattr("postgres.session.init_engine", _boom)
        monkeypatch.setattr("graph.client.init_driver", _boom_async)
        await _init_stores()  # must not raise — room keeps running

    async def test_pg_down_neo4j_up(self, monkeypatch) -> None:
        def _boom(*a, **k):
            raise RuntimeError("postgres down")

        init_driver = AsyncMock()
        monkeypatch.setattr("postgres.session.init_engine", _boom)
        monkeypatch.setattr("graph.client.init_driver", init_driver)
        await _init_stores()
        init_driver.assert_awaited_once()


class TestEntrypoint:
    def test_entrypoint_is_async_handler(self) -> None:
        import inspect

        assert callable(entrypoint)
        assert inspect.iscoroutinefunction(entrypoint)
