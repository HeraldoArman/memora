"""Frame sampler — 1 FPS from a LiveKit VideoStream.

Yields (frame_number, bgr_jpeg_bytes, bgr_np) at FRAME_SAMPLE_FPS. Drives both the face
recognizer (InsightFace, on the BGR numpy array) and Gemini Live video (the JPEG bytes).
LiveKit VideoFrame → BGRA → numpy → BGR + JPEG. The sampler does NOT own the recognizer or
Gemini session — it just produces frames; the observation engine consumes them.
"""

from __future__ import annotations

import asyncio
import logging

import numpy as np

from constants import FRAME_SAMPLE_FPS

logger = logging.getLogger(__name__)


class FrameSampler:
    """Pull frames from a LiveKit VideoStream at a capped rate."""

    def __init__(self, video_stream, *, fps: float = FRAME_SAMPLE_FPS) -> None:
        self.video_stream = video_stream
        self.interval = 1.0 / fps
        self.frame_no = 0

    async def frames(self):
        """Async generator over sampled frames. Each yielded item: dict with keys
        frame_no, bgr (np.ndarray HxWx3 uint8), jpeg (bytes).

        LiveKit VideoStream yields events with a .frame attribute (VideoFrame). We convert
        to BGRA → numpy → BGR, then JPEG-encode.
        """
        from livekit import rtc

        last_emit = None
        async for ev in self.video_stream:
            frame = getattr(ev, "frame", ev)
            now = asyncio.get_event_loop().time()
            # ponytail: None sentinel so the first frame always emits. A 0.0
            # sentinel breaks when the monotonic clock is still near 0.0 (fresh
            # loop on a fast/loaded CI runner): `now - 0.0 < interval` is True
            # and the first frame gets skipped → 0 frames yielded.
            if last_emit is not None and now - last_emit < self.interval:
                continue
            last_emit = now
            argb = frame.convert(rtc.VideoBufferType.BGRA).data
            h, w = frame.height, frame.width
            bgra = np.frombuffer(argb, dtype=np.uint8).reshape(h, w, 4)
            bgr = bgra[:, :, :3]  # drop alpha; BGRA→BGR
            jpeg = _encode_jpeg(bgr)
            self.frame_no += 1
            yield {"frame_no": self.frame_no, "bgr": bgr, "jpeg": jpeg}


def _encode_jpeg(bgr: np.ndarray) -> bytes:
    import cv2

    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return buf.tobytes()


# --- self-check: encode/decode roundtrip ---
def _self_check() -> None:  # pragma: no cover
    import cv2

    img = (np.random.default_rng(0).random((64, 64, 3)) * 255).astype(np.uint8)
    jpg = _encode_jpeg(img)
    dec = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    assert dec.shape == (64, 64, 3), dec.shape
    print(f"sampler self-check OK: jpeg {len(jpg)} bytes, decoded {dec.shape}")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
