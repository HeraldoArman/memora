"""Unit tests — gateway: RoomSession lifecycle, track_handler face lookup + audio shim,
entrypoint _init_stores graceful degradation.

refactor/bare-minimum: no observation engine, no working memory, no on_extract.
Tests verify the stripped-down RoomSession + _update_last_face + audio shim.

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
from gateway.livekit.track_handler import _AudioShim, _update_last_face
from gateway.session import RoomSession
from tools import ToolContext


def _face_repo() -> FaceRepository:
    repo = FaceRepository(FaceIndex(dim=8), known_threshold=0.50, possible_threshold=0.35)
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
        self.started = False

    async def start(self, current=None) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False


class TestRoomSessionCreate:
    async def test_create_wires_collaborators(self, monkeypatch) -> None:
        repo = _patch_face_repo(monkeypatch)
        monkeypatch.setattr("gateway.session.ReasoningAgent", _FakeAgent)
        monkeypatch.setattr("perception.face.recognizer.preload", lambda: None)
        room = MagicMock()
        session = await RoomSession.create(room)
        assert session.face_repo is repo
        assert session.tool_ctx.face_repo is session.face_repo
        assert session.agent.room is room
        assert session.agent.ctx is session.tool_ctx
        assert session.tool_ctx.last_face is None  # no face detected yet


class TestRoomSessionLifecycle:
    def _session(self) -> RoomSession:
        ctx = ToolContext()
        agent = MagicMock()
        agent.start = AsyncMock()
        agent.stop = AsyncMock()
        return RoomSession(tool_ctx=ctx, agent=agent)

    async def test_start(self) -> None:
        s = self._session()
        s.agent.start = AsyncMock()
        await s.start()
        s.agent.start.assert_awaited_once()

    async def test_stop_cancels_tasks_and_stops(self) -> None:
        s = self._session()
        cancelled = []

        class _T:
            def cancel(self):
                cancelled.append(True)

        s.tasks = [_T()]
        s.agent.stop = AsyncMock()
        await s.stop()
        assert cancelled == [True]
        s.agent.stop.assert_awaited_once()


class TestUpdateLastFace:
    """Tests _update_last_face — the bare-minimum replacement for _lookup_face."""

    def _session(self, repo: FaceRepository | None = None) -> SimpleNamespace:
        ctx = ToolContext(face_repo=repo)
        return SimpleNamespace(face_repo=repo, tool_ctx=ctx)

    async def test_none_repo(self) -> None:
        session = self._session(None)
        detected = SimpleNamespace(embedding=np.zeros(8, dtype=np.float32))
        await _update_last_face(detected, session)
        assert session.tool_ctx.last_face is None  # no repo → no update

    async def test_known_resolves_name(self) -> None:
        repo = _face_repo()
        session = self._session(repo)
        v = np.zeros(8, dtype=np.float32)
        v[0] = 1.0
        detected = SimpleNamespace(embedding=v)
        with patch("graph.repository.PersonRepo") as mock_repo_cls:
            mock_repo_cls.return_value.get_person = AsyncMock(return_value={"name": "Asep"})
            await _update_last_face(detected, session)
        lf = session.tool_ctx.last_face
        assert lf is not None
        assert lf["person_id"] == "person-1"
        assert lf["name"] == "Asep"
        assert lf["is_known"] is True

    async def test_graph_down_keeps_face(self) -> None:
        repo = _face_repo()
        session = self._session(repo)
        v = np.zeros(8, dtype=np.float32)
        v[0] = 1.0
        detected = SimpleNamespace(embedding=v)
        with patch("graph.repository.PersonRepo") as mock_repo_cls:
            mock_repo_cls.return_value.get_person = AsyncMock(
                side_effect=RuntimeError("neo4j down")
            )
            await _update_last_face(detected, session)
        lf = session.tool_ctx.last_face
        assert lf is not None
        assert lf["person_id"] == "person-1"
        assert lf["name"] is None  # degraded, not dropped
        assert lf["is_known"] is True

    async def test_unknown_face(self) -> None:
        repo = _face_repo()
        session = self._session(repo)
        unknown = np.zeros(8, dtype=np.float32)
        unknown[1] = 1.0  # orthogonal → unknown
        detected = SimpleNamespace(embedding=unknown)
        await _update_last_face(detected, session)
        lf = session.tool_ctx.last_face
        assert lf is not None
        assert lf["person_id"] is None
        assert lf["is_known"] is False

    async def test_possible_match_resolves_name(self) -> None:
        repo = _face_repo()
        session = self._session(repo)
        partial = np.zeros(8, dtype=np.float32)
        partial[0] = 0.42
        partial[1] = float(np.sqrt(1 - 0.42**2))
        detected = SimpleNamespace(embedding=partial)
        with patch("graph.repository.PersonRepo") as mock_repo_cls:
            mock_repo_cls.return_value.get_person = AsyncMock(return_value={"name": "Asep"})
            await _update_last_face(detected, session)
        lf = session.tool_ctx.last_face
        assert lf is not None
        assert lf["person_id"] == "person-1"
        assert lf["name"] == "Asep"
        assert lf["is_known"] is False
        assert lf["is_possible"] is True


class TestAudioShim:
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
