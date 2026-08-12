"""Unit tests — Video Bridge session (gateway/video_bridge/session).

Pure dataclass/queue logic — no LiveKit, no cv2, no network.
"""

from __future__ import annotations

from gateway.video_bridge.session import VideoSession


class TestVideoSessionPushFrame:
    def test_first_frame_accepted(self) -> None:
        session = VideoSession(device_id="dev1", room_name="room1")
        session.push_frame(b"\xff\xd8fake\xff\xd9")
        assert session.received_frames == 1
        assert session.dropped_frames == 0
        assert not session.queue.empty()

    def test_second_frame_drops_first(self) -> None:
        """Queue maxsize=1 — pushing when full drops the old frame."""
        session = VideoSession(device_id="dev1", room_name="room1")
        session.push_frame(b"frame-1")
        session.push_frame(b"frame-2")
        assert session.received_frames == 2
        assert session.dropped_frames == 1
        # newest frame is in the queue
        item = session.queue.get_nowait()
        assert item == b"frame-2"

    def test_metrics_track_bytes(self) -> None:
        session = VideoSession(device_id="dev1", room_name="room1")
        session.push_frame(b"\x00" * 100)
        session.push_frame(b"\x00" * 200)
        assert session.total_jpeg_bytes == 300
        assert session.average_jpeg_bytes == 150.0

    def test_last_frame_age_ms(self) -> None:
        session = VideoSession(device_id="dev1", room_name="room1")
        assert session.last_frame_age_ms is None
        session.push_frame(b"data")
        assert session.last_frame_age_ms is not None
        assert session.last_frame_age_ms >= 0

    def test_average_decode_ms_no_frames(self) -> None:
        session = VideoSession(device_id="dev1", room_name="room1")
        assert session.average_decode_ms == 0.0

    def test_average_jpeg_bytes_no_frames(self) -> None:
        session = VideoSession(device_id="dev1", room_name="room1")
        assert session.average_jpeg_bytes == 0.0
