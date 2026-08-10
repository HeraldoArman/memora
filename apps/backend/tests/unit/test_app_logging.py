"""Unit tests — FastAPI factory + health route + logging setup.

No DB/network: stores uninitialized → health reports degraded but never raises.
create_app is inspected structurally (no TestClient, keeps test dep-free).
"""

from __future__ import annotations

import logging

from api.app import create_app
from api.routes.health import health


class TestCreateApp:
    def test_app_shape(self) -> None:
        app = create_app()
        assert app.title == "Memora"
        assert app.version == "0.1.0"

    def test_health_route_registered_get(self) -> None:
        from api.routes.health import router as health_router

        matches = [r for r in health_router.routes if getattr(r, "path", None) == "/health"]
        assert len(matches) == 1
        assert "GET" in getattr(matches[0], "methods", [])


class _FakeAppState:
    face_index = None


class _FakeRequest:
    app = type("App", (), {"state": _FakeAppState})()


class TestHealthRoute:
    async def test_uninitialized_stores_degrade_not_crash(self) -> None:
        import asyncio

        from graph import client as neo4j_client

        from postgres import session as pg_session

        try:
            await asyncio.gather(pg_session.close_engine(), neo4j_client.close_driver())
        except RuntimeError:
            pass
        resp = await health(_FakeRequest())
        assert resp.status_code == 503  # degraded → 503, not 200
        out = _body(resp)
        assert out["status"] == "degraded"
        assert out["postgres"].startswith("error:")
        assert out["neo4j"] == "error"
        assert out["faiss"] == "unloaded"

    async def test_loaded_faiss_reports_size(self) -> None:
        req = _FakeRequest()

        class _Idx:
            size = 5

        req.app.state.face_index = _Idx()
        resp = await health(req)
        out = _body(resp)
        assert out["faiss"] == "ok:ntotal=5"


def _body(resp) -> dict:
    import json

    return json.loads(resp.body)


class TestSetupLogging:
    def _cleanup(self) -> None:
        root = logging.getLogger()
        root.handlers.clear()

    def test_clears_and_sets_stderr(self, settings) -> None:
        self._cleanup()
        try:
            from config.logging import setup_logging

            setup_logging(level="DEBUG")
            root = logging.getLogger()
            assert root.level == logging.DEBUG
            assert any(type(h) is logging.StreamHandler for h in root.handlers)
            # chatty SDKs capped
            assert logging.getLogger("livekit").level == logging.WARNING
            assert logging.getLogger("faiss").level == logging.WARNING
            # our packages follow root
            assert logging.getLogger("pipeline").level == logging.DEBUG
        finally:
            self._cleanup()

    def test_file_handler_when_log_file(self, settings, tmp_path) -> None:
        self._cleanup()
        try:
            from config.logging import setup_logging

            logfile = tmp_path / "sub" / "memora.log"
            setup_logging(level="INFO", log_file=str(logfile))
            assert logfile.exists()
            root = logging.getLogger()
            assert any(type(h) is logging.handlers.RotatingFileHandler for h in root.handlers)
        finally:
            self._cleanup()

    def test_idempotent_no_duplicate_handlers(self, settings) -> None:
        self._cleanup()
        try:
            from config.logging import setup_logging

            setup_logging()
            setup_logging()  # uvicorn reload simulation
            root = logging.getLogger()
            stderr_handlers = [h for h in root.handlers if type(h) is logging.StreamHandler]
            assert len(stderr_handlers) == 1
        finally:
            self._cleanup()
