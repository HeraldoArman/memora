"""Unit tests — gateway: entrypoint + track_handler face lookup + _init_stores.

Replaces the old RoomSession/AudioShim tests. The new architecture uses
AgentSession + RealtimeModel, so there's no RoomSession or AudioShim. We test:
  - entrypoint is an async handler
  - _init_stores graceful degradation (unchanged)
  - _update_last_face with tool_ctx directly (signature changed from session)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
from vector.index import FaceIndex
from vector.repository import FaceRepository

from gateway.livekit.entrypoint import _init_stores, entrypoint
from gateway.livekit.track_handler import _update_last_face
from tools import ToolContext


def _face_repo() -> FaceRepository:
    repo = FaceRepository(FaceIndex(dim=8), known_threshold=0.50, possible_threshold=0.35)
    v = np.zeros(8, dtype=np.float32)
    v[0] = 1.0
    repo.register(v, "person-1")
    return repo


class TestUpdateLastFace:
    """Tests _update_last_face — now takes tool_ctx directly (was session)."""

    def _ctx(self, repo: FaceRepository | None = None) -> ToolContext:
        return ToolContext(face_repo=repo)

    async def test_none_repo(self) -> None:
        ctx = self._ctx(None)
        detected = SimpleNamespace(embedding=np.zeros(8, dtype=np.float32))
        await _update_last_face(detected, ctx)
        assert ctx.last_face is None

    async def test_known_resolves_name(self) -> None:
        repo = _face_repo()
        ctx = self._ctx(repo)
        v = np.zeros(8, dtype=np.float32)
        v[0] = 1.0
        detected = SimpleNamespace(embedding=v)
        with patch("graph.repository.PersonRepo") as mock_repo_cls:
            mock_repo_cls.return_value.get_person = AsyncMock(return_value={"name": "Asep"})
            await _update_last_face(detected, ctx)
        lf = ctx.last_face
        assert lf is not None
        assert lf["person_id"] == "person-1"
        assert lf["name"] == "Asep"
        assert lf["is_known"] is True

    async def test_graph_down_keeps_face(self) -> None:
        repo = _face_repo()
        ctx = self._ctx(repo)
        v = np.zeros(8, dtype=np.float32)
        v[0] = 1.0
        detected = SimpleNamespace(embedding=v)
        with patch("graph.repository.PersonRepo") as mock_repo_cls:
            mock_repo_cls.return_value.get_person = AsyncMock(
                side_effect=RuntimeError("neo4j down")
            )
            await _update_last_face(detected, ctx)
        lf = ctx.last_face
        assert lf is not None
        assert lf["person_id"] == "person-1"
        assert lf["name"] is None
        assert lf["is_known"] is True

    async def test_unknown_face(self) -> None:
        repo = _face_repo()
        ctx = self._ctx(repo)
        unknown = np.zeros(8, dtype=np.float32)
        unknown[1] = 1.0
        detected = SimpleNamespace(embedding=unknown)
        await _update_last_face(detected, ctx)
        lf = ctx.last_face
        assert lf is not None
        assert lf["person_id"] is None
        assert lf["is_known"] is False

    async def test_possible_match_resolves_name(self) -> None:
        repo = _face_repo()
        ctx = self._ctx(repo)
        partial = np.zeros(8, dtype=np.float32)
        partial[0] = 0.42
        partial[1] = float(np.sqrt(1 - 0.42**2))
        detected = SimpleNamespace(embedding=partial)
        with patch("graph.repository.PersonRepo") as mock_repo_cls:
            mock_repo_cls.return_value.get_person = AsyncMock(return_value={"name": "Asep"})
            await _update_last_face(detected, ctx)
        lf = ctx.last_face
        assert lf is not None
        assert lf["person_id"] == "person-1"
        assert lf["name"] == "Asep"
        assert lf["is_known"] is False
        assert lf["is_possible"] is True


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
        await _init_stores()

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
