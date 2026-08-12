"""Unit tests — dashboard router registration + route shapes.

Structural: no DB, no TestClient. Asserts the dashboard router exists and that
each sub-route is registered as a GET endpoint. Unwraps _IncludedRouter wrappers
to find the actual APIRoute objects.
"""

from __future__ import annotations

from api.routes.dashboard import router as dashboard_router


def _flatten_routes(router) -> list:
    """Recursively unwrap _IncludedRouter → original_router to find APIRoute objects.
    The /api/dashboard prefix is set on the parent router, so we prepend it to
    each sub-route's path."""
    routes: list = []
    for r in router.routes:
        if hasattr(r, "original_router"):
            routes.extend(_flatten_routes(r.original_router))
        else:
            routes.append(r)
    return routes


_PREFIX = "/api/dashboard"


def _full_paths(router) -> set[str]:
    return {f"{_PREFIX}{getattr(r, 'path', '')}" for r in _flatten_routes(router)}


class TestDashboardRouterWired:
    def test_dashboard_prefix_present(self) -> None:
        paths = _full_paths(dashboard_router)
        assert any(p.startswith("/api/dashboard") for p in paths)

    def test_all_dashboard_endpoints_registered(self) -> None:
        paths = _full_paths(dashboard_router)
        expected = {
            "/api/dashboard/graph",
            "/api/dashboard/persons",
            "/api/dashboard/memories",
            "/api/dashboard/conversations",
            "/api/dashboard/conversations/{session_id}/messages",
            "/api/dashboard/reminders/today",
            "/api/dashboard/reminders/upcoming",
            "/api/dashboard/events/upcoming",
            "/api/dashboard/shopping",
            "/api/dashboard/settings",
            "/api/dashboard/health",
        }
        missing = expected - paths
        assert not missing, f"Missing dashboard routes: {missing}"

    def test_all_dashboard_endpoints_are_get(self) -> None:
        routes = _flatten_routes(dashboard_router)
        assert len(routes) > 0
        for r in routes:
            methods = getattr(r, "methods", set())
            assert "GET" in methods, f"{getattr(r, 'path', '?')} is not GET: {methods}"


class TestDashboardHealthRoute:
    async def test_degraded_when_no_stores(self) -> None:
        """Health route should return 503 degraded when DBs are not initialized."""
        import asyncio

        from graph import client as neo4j_client

        from api.routes.dashboard import health as health_module
        from postgres import session as pg_session

        try:
            await asyncio.gather(pg_session.close_engine(), neo4j_client.close_driver())
        except RuntimeError:
            pass

        class _FakeAppState:
            face_index = None

        class _FakeRequest:
            app = type("App", (), {"state": _FakeAppState})()

        resp = await health_module.dashboard_health(_FakeRequest())
        assert resp.status_code == 503
        import json

        body = json.loads(resp.body)
        assert body["status"] == "degraded"
        assert "postgres" in body
        assert body["neo4j"] == "error"

    async def test_faiss_size_reported(self) -> None:
        from api.routes.dashboard import health as health_module

        class _Idx:
            size = 7

        class _FakeAppState:
            face_index = _Idx()

        class _FakeRequest:
            app = type("App", (), {"state": _FakeAppState})()

        resp = await health_module.dashboard_health(_FakeRequest())
        import json

        body = json.loads(resp.body)
        assert body["faiss"] == "ok:ntotal=7"
