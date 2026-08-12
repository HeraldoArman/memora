"""VideoSession — per-device state for the JPEG→H.264 bridge.

Queue maxsize=1: drop old frame if encoder is busy, keep newest. At 1 FPS
this is instant. A longer buffer only adds latency.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class VideoSession:
    device_id: str
    room_name: str
    width: int = 640
    height: int = 480
    queue: asyncio.Queue[bytes] = field(default_factory=lambda: asyncio.Queue(maxsize=1))
    received_frames: int = 0
    decoded_frames: int = 0
    dropped_frames: int = 0
    published_frames: int = 0
    decode_errors: int = 0
    last_frame_at: float | None = None
    total_jpeg_bytes: int = 0
    total_decode_ms: float = 0.0

    def push_frame(self, jpeg: bytes) -> None:
        """Push a JPEG frame into the queue. Drops old frame if full."""
        self.received_frames += 1
        self.total_jpeg_bytes += len(jpeg)
        self.last_frame_at = time.monotonic()
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self.dropped_frames += 1
        try:
            self.queue.put_nowait(jpeg)
        except asyncio.QueueFull:
            self.dropped_frames += 1

    @property
    def average_jpeg_bytes(self) -> float:
        return self.total_jpeg_bytes / self.received_frames if self.received_frames else 0.0

    @property
    def average_decode_ms(self) -> float:
        return self.total_decode_ms / self.decoded_frames if self.decoded_frames else 0.0

    @property
    def last_frame_age_ms(self) -> float | None:
        if self.last_frame_at is None:
            return None
        return (time.monotonic() - self.last_frame_at) * 1000
