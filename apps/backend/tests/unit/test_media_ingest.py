"""Unit tests — media ingest endpoint (api/routes/media).

Tests the FastAPI route in isolation: JPEG validation, size limits, marker
checks, bridge wiring. No live LiveKit connection — _ensure_bridge is mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.routes.media import JPEG_END, JPEG_START, MAX_JPEG_SIZE


def _valid_jpeg(size: int = 100) -> bytes:
    """Build a minimal valid JPEG byte sequence (markers + padding)."""
    return JPEG_START + b"\x00" * (size - 4) + JPEG_END


@pytest.fixture
def _clean_bridges():
    """Clear the module-level bridge registry before and after each test."""
    from api.routes import media as media_mod

    media_mod._bridges.clear()
    yield
    media_mod._bridges.clear()


class TestIngestFrameValidation:
    """JPEG validation logic — runs the route handler directly with mocked Request."""

    async def test_valid_jpeg_accepted(self, _clean_bridges) -> None:
        from api.routes.media import ingest_frame

        jpeg = _valid_jpeg(100)
        req = MagicMock()
        req.body = AsyncMock(return_value=jpeg)

        with patch("api.routes.media._ensure_bridge", new_callable=AsyncMock) as mock_bridge:
            mock_bridge.return_value = MagicMock()
            resp = await ingest_frame(
                req,
                x_memora_device_id="memora-device",
                x_frame_id="1",
                x_capture_time_ms="1000",
                x_width="640",
                x_height="480",
            )
        assert resp.status_code == 202
        mock_bridge.assert_awaited_once()

    async def test_oversized_jpeg_rejected(self, _clean_bridges) -> None:
        from fastapi import HTTPException

        from api.routes.media import ingest_frame

        jpeg = _valid_jpeg(MAX_JPEG_SIZE + 1)
        req = MagicMock()
        req.body = AsyncMock(return_value=jpeg)

        with pytest.raises(HTTPException) as exc_info:
            await ingest_frame(
                req,
                x_memora_device_id="memora-device",
                x_frame_id="1",
                x_capture_time_ms="1000",
                x_width="640",
                x_height="480",
            )
        assert exc_info.value.status_code == 413

    async def test_bad_markers_rejected(self, _clean_bridges) -> None:
        from fastapi import HTTPException

        from api.routes.media import ingest_frame

        req = MagicMock()
        req.body = AsyncMock(return_value=b"not a jpeg at all")

        with pytest.raises(HTTPException) as exc_info:
            await ingest_frame(
                req,
                x_memora_device_id="memora-device",
                x_frame_id="1",
                x_capture_time_ms="1000",
                x_width="640",
                x_height="480",
            )
        assert exc_info.value.status_code == 400

    async def test_empty_body_rejected(self, _clean_bridges) -> None:
        from fastapi import HTTPException

        from api.routes.media import ingest_frame

        req = MagicMock()
        req.body = AsyncMock(return_value=b"")

        with pytest.raises(HTTPException) as exc_info:
            await ingest_frame(
                req,
                x_memora_device_id="memora-device",
                x_frame_id="1",
                x_capture_time_ms="1000",
                x_width="640",
                x_height="480",
            )
        assert exc_info.value.status_code == 400

    async def test_missing_start_marker_rejected(self, _clean_bridges) -> None:
        from fastapi import HTTPException

        from api.routes.media import ingest_frame

        req = MagicMock()
        req.body = AsyncMock(return_value=b"\x00\x00" + JPEG_END)

        with pytest.raises(HTTPException) as exc_info:
            await ingest_frame(
                req,
                x_memora_device_id="memora-device",
                x_frame_id="1",
                x_capture_time_ms="1000",
                x_width="640",
                x_height="480",
            )
        assert exc_info.value.status_code == 400


class TestIngestFrameBridgeWiring:
    """Verify the route pushes frames to the bridge when one exists."""

    async def test_push_frame_called(self, _clean_bridges) -> None:
        from api.routes.media import ingest_frame

        jpeg = _valid_jpeg(50)
        req = MagicMock()
        req.body = AsyncMock(return_value=jpeg)

        mock_bridge = MagicMock()
        with patch("api.routes.media._ensure_bridge", new_callable=AsyncMock) as mock_ensure:
            mock_ensure.return_value = mock_bridge
            resp = await ingest_frame(
                req,
                x_memora_device_id="memora-device",
                x_frame_id="42",
                x_capture_time_ms="1000",
                x_width="640",
                x_height="480",
            )
        assert resp.status_code == 202
        mock_bridge.push_frame.assert_called_once_with(jpeg)

    async def test_bridge_exception_does_not_fail_request(self, _clean_bridges) -> None:
        from api.routes.media import ingest_frame

        jpeg = _valid_jpeg(50)
        req = MagicMock()
        req.body = AsyncMock(return_value=jpeg)

        mock_bridge = MagicMock()
        mock_bridge.push_frame.side_effect = RuntimeError("bridge down")
        with patch("api.routes.media._ensure_bridge", new_callable=AsyncMock) as mock_ensure:
            mock_ensure.return_value = mock_bridge
            resp = await ingest_frame(
                req,
                x_memora_device_id="memora-device",
                x_frame_id="42",
                x_capture_time_ms="1000",
                x_width="640",
                x_height="480",
            )
        # 202 even if bridge crashes — ESP gets ack, doesn't retry spam
        assert resp.status_code == 202


class TestMediaRouterRegistration:
    """Structural test — verify the media router is registered with correct prefix."""

    def test_media_router_prefix(self) -> None:
        from api.routes.media import router

        assert router.prefix == "/api/media"

    def test_frame_endpoint_exists(self) -> None:
        from api.routes.media import router

        paths = {getattr(r, "path", "") for r in router.routes}
        assert "/api/media/video/frame" in paths

    def test_frame_endpoint_is_post(self) -> None:
        from api.routes.media import router

        for r in router.routes:
            if getattr(r, "path", "") == "/api/media/video/frame":
                assert "POST" in r.methods
                return
        pytest.fail("POST /api/media/video/frame not found")

    def test_media_router_in_app(self) -> None:
        """Verify the media router is included in the FastAPI app factory."""
        from api.app import create_app

        app = create_app()

        # FastAPI wraps included routers in _IncludedRouter; unwrap to find routes
        def _all_routes(application):
            for r in application.routes:
                if hasattr(r, "original_router"):
                    yield from _all_routes(r.original_router)
                elif hasattr(r, "routes"):
                    yield from r.routes
                else:
                    yield r

        media_paths = [
            getattr(r, "path", "")
            for r in _all_routes(app)
            if hasattr(r, "path") and "/api/media" in getattr(r, "path", "")
        ]
        assert any("/video/frame" in p for p in media_paths)
