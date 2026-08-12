"""Unit tests — Video Bridge LiveKit publisher (gateway/video_bridge/bridge).

Mocks rtc.Room, rtc.VideoSource, rtc.LocalVideoTrack — no real LiveKit
connection. Tests the JPEG decode → capture_frame path and lifecycle.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np


def _fake_jpeg(width=4, height=4) -> bytes:
    """Build a tiny valid JPEG using cv2."""
    import cv2

    img = (np.random.default_rng(0).random((height, width, 3)) * 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


class TestVideoBridgeStart:
    """Tests VideoBridge.start() — mocks LiveKit connection + track publish."""

    async def test_start_connects_and_publishes(self) -> None:
        from gateway.video_bridge.bridge import VideoBridge

        bridge = VideoBridge(
            device_id="dev1",
            room_name="room1",
            width=640,
            height=480,
            livekit_url="wss://fake",
            livekit_api_key="key",
            livekit_api_secret="secret",
        )

        with (
            patch("gateway.video_bridge.bridge.api") as mock_api,
            patch("gateway.video_bridge.bridge.rtc") as mock_rtc,
        ):
            mock_token = MagicMock()
            mock_token.with_identity.return_value = mock_token
            mock_token.with_name.return_value = mock_token
            mock_token.with_grants.return_value = mock_token
            mock_token.to_jwt.return_value = "fake-token"
            mock_api.AccessToken.return_value = mock_token

            mock_room = MagicMock()
            mock_room.connect = AsyncMock()
            mock_room.local_participant.publish_track = AsyncMock(
                return_value=MagicMock(sid="TR_xxx")
            )
            mock_rtc.Room.return_value = mock_room
            mock_rtc.VideoSource.return_value = MagicMock()
            mock_rtc.LocalVideoTrack.create_video_track.return_value = MagicMock()
            mock_rtc.TrackPublishOptions.return_value = MagicMock()
            mock_rtc.TrackSource.SOURCE_CAMERA = 1
            mock_rtc.VideoCodec.H264 = 1
            mock_rtc.VideoEncoding.return_value = MagicMock()

            await bridge.start()

        mock_room.connect.assert_awaited_once()
        mock_room.local_participant.publish_track.assert_awaited_once()
        assert bridge._started is True
        assert bridge._task is not None

        # cleanup
        bridge._task.cancel()
        try:
            await bridge._task
        except asyncio.CancelledError:
            pass

    async def test_identity_format(self) -> None:
        from gateway.video_bridge.bridge import VideoBridge

        bridge = VideoBridge(
            device_id="memora-device",
            room_name="room1",
            width=640,
            height=480,
            livekit_url="wss://fake",
            livekit_api_key="key",
            livekit_api_secret="secret",
        )
        assert bridge.identity == "memora-video-bridge-memora-device"


class TestVideoBridgeFrameLoop:
    """Tests _frame_loop — JPEG decode → capture_frame path."""

    async def test_decodes_and_publishes_frame(self) -> None:
        from gateway.video_bridge.bridge import VideoBridge

        bridge = VideoBridge(
            device_id="dev1",
            room_name="room1",
            width=4,
            height=4,
            livekit_url="wss://fake",
            livekit_api_key="key",
            livekit_api_secret="secret",
        )

        mock_source = MagicMock()
        bridge._source = mock_source

        jpeg = _fake_jpeg(4, 4)
        await bridge.session.queue.put(jpeg)

        # Run one iteration of the frame loop
        task = asyncio.create_task(bridge._frame_loop())
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert bridge.session.decoded_frames == 1
        assert bridge.session.published_frames == 1
        assert bridge.session.decode_errors == 0
        mock_source.capture_frame.assert_called_once()

    async def test_bad_jpeg_increments_decode_errors(self) -> None:
        from gateway.video_bridge.bridge import VideoBridge

        bridge = VideoBridge(
            device_id="dev1",
            room_name="room1",
            width=4,
            height=4,
            livekit_url="wss://fake",
            livekit_api_key="key",
            livekit_api_secret="secret",
        )

        bridge._source = MagicMock()
        await bridge.session.queue.put(b"\xff\xd8notreallyjpeg\xff\xd9")

        task = asyncio.create_task(bridge._frame_loop())
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert bridge.session.decode_errors == 1
        assert bridge.session.decoded_frames == 0
        bridge._source.capture_frame.assert_not_called()

    async def test_frame_loop_resizes_mismatched_dimensions(self) -> None:
        from gateway.video_bridge.bridge import VideoBridge

        bridge = VideoBridge(
            device_id="dev1",
            room_name="room1",
            width=8,
            height=8,
            livekit_url="wss://fake",
            livekit_api_key="key",
            livekit_api_secret="secret",
        )

        mock_source = MagicMock()
        bridge._source = mock_source

        # 4x4 JPEG but bridge expects 8x8
        jpeg = _fake_jpeg(4, 4)
        await bridge.session.queue.put(jpeg)

        task = asyncio.create_task(bridge._frame_loop())
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert bridge.session.decoded_frames == 1
        # Verify the frame passed to capture_frame has correct dimensions
        frame_arg = mock_source.capture_frame.call_args.args[0]
        assert frame_arg.width == 8
        assert frame_arg.height == 8

    async def test_push_frame_to_bridge(self) -> None:
        """push_frame delegates to session.push_frame."""
        from gateway.video_bridge.bridge import VideoBridge

        bridge = VideoBridge(
            device_id="dev1",
            room_name="room1",
            width=4,
            height=4,
            livekit_url="wss://fake",
            livekit_api_key="key",
            livekit_api_secret="secret",
        )
        jpeg = _fake_jpeg(4, 4)
        bridge.push_frame(jpeg)
        assert bridge.session.received_frames == 1
        assert not bridge.session.queue.empty()


class TestVideoBridgeStop:
    async def test_stop_cleans_up(self) -> None:
        from gateway.video_bridge.bridge import VideoBridge

        bridge = VideoBridge(
            device_id="dev1",
            room_name="room1",
            width=4,
            height=4,
            livekit_url="wss://fake",
            livekit_api_key="key",
            livekit_api_secret="secret",
        )

        bridge._source = MagicMock()
        bridge._source.aclose = AsyncMock()
        bridge._room = MagicMock()
        bridge._room.disconnect = AsyncMock()
        bridge._task = asyncio.create_task(asyncio.sleep(100))
        bridge._started = True

        await bridge.stop()

        assert bridge._started is False
        assert bridge._source is None
        assert bridge._room is None
        bridge._source is None  # source aclosed + nulled
