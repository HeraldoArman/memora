"""VideoBridge — joins a LiveKit room and publishes JPEG frames as H.264 video.

Receives JPEG bytes via push_frame(), decodes to RGB24 via cv2, feeds to
rtc.VideoSource.capture_frame(). LiveKit SDK handles the H.264 encoding.

Runs as a background asyncio task inside the FastAPI process. When the
LiveKit connection drops, reconnects automatically (rtc.Room handles this).
"""

from __future__ import annotations

import asyncio
import logging
import time

import cv2
import numpy as np
from livekit import api, rtc

from gateway.video_bridge.session import VideoSession

log = logging.getLogger(__name__)


class VideoBridge:
    """Per-device JPEG→H.264 bridge publishing to LiveKit."""

    def __init__(
        self,
        device_id: str,
        room_name: str,
        width: int,
        height: int,
        livekit_url: str,
        livekit_api_key: str,
        livekit_api_secret: str,
    ) -> None:
        self.device_id = device_id
        self.identity = f"memora-video-bridge-{device_id}"
        self.room_name = room_name
        self.width = width
        self.height = height
        self.livekit_url = livekit_url
        self.api_key = livekit_api_key
        self.api_secret = livekit_api_secret
        self.session = VideoSession(
            device_id=device_id, room_name=room_name, width=width, height=height
        )
        self._room: rtc.Room | None = None
        self._source: rtc.VideoSource | None = None
        self._task: asyncio.Task | None = None
        self._started = False

    async def start(self) -> None:
        """Connect to LiveKit, publish H.264 track, start frame loop."""
        log.info(
            "video_bridge starting: device=%s room=%s identity=%s",
            self.device_id,
            self.room_name,
            self.identity,
        )

        token = (
            api.AccessToken(self.api_key, self.api_secret)
            .with_identity(self.identity)
            .with_name(self.identity)
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=self.room_name,
                    can_publish=True,
                    can_subscribe=False,
                )
            )
            .to_jwt()
        )

        self._room = rtc.Room()
        await self._room.connect(self.livekit_url, token)
        log.info("video bridge connected: room=%s identity=%s", self.room_name, self.identity)

        self._source = rtc.VideoSource(self.width, self.height)
        track = rtc.LocalVideoTrack.create_video_track("camera-h264", self._source)
        options = rtc.TrackPublishOptions(
            source=rtc.TrackSource.SOURCE_CAMERA,
            video_codec=rtc.VideoCodec.H264,
            video_encoding=rtc.VideoEncoding(
                max_framerate=1,
                max_bitrate=300_000,
            ),
        )
        publication = await self._room.local_participant.publish_track(track, options)
        log.info("h264 track published: sid=%s device=%s", publication.sid, self.device_id)

        self._task = asyncio.create_task(self._frame_loop(), name=f"video-bridge-{self.device_id}")
        self._started = True
        log.info("video_bridge started: device=%s", self.device_id)

    def push_frame(self, jpeg: bytes) -> None:
        """Push a JPEG frame from the HTTP ingest endpoint."""
        self.session.push_frame(jpeg)

    async def _frame_loop(self) -> None:
        """Decode JPEG → RGB24 → capture_frame, forever."""
        while True:
            try:
                jpeg_bytes = await self.session.queue.get()
                # ponytail: queue depth at dequeue tells us if ingest outruns publish
                # (device pushes faster than we can decode+encode) or if the frame
                # sat queued (device slow / network gap). Both show up as "slow H264".
                queue_depth = self.session.queue.qsize()
                frame_age_ms = self.session.last_frame_age_ms or 0.0
                t0 = time.perf_counter()

                np_arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
                bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if bgr is None:
                    self.session.decode_errors += 1
                    log.warning("jpeg decode failed: device=%s", self.device_id)
                    continue

                if bgr.shape[1] != self.width or bgr.shape[0] != self.height:
                    bgr = cv2.resize(bgr, (self.width, self.height), interpolation=cv2.INTER_AREA)

                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                frame = rtc.VideoFrame(
                    self.width,
                    self.height,
                    rtc.VideoBufferType.RGB24,
                    rgb.tobytes(),
                )

                if self._source is not None:
                    self._source.capture_frame(frame)

                self.session.decoded_frames += 1
                self.session.published_frames += 1
                decode_ms = (time.perf_counter() - t0) * 1000
                self.session.total_decode_ms += decode_ms

                log.info(
                    "h264 frame published device=%s frame=%d decode_ms=%.1f jpeg_bytes=%d "
                    "queue_depth=%d frame_age_ms=%.1f",
                    self.device_id,
                    self.session.published_frames,
                    decode_ms,
                    len(jpeg_bytes),
                    queue_depth,
                    frame_age_ms,
                )

                del bgr, rgb, np_arr, jpeg_bytes

            except asyncio.CancelledError:
                log.info("video bridge frame loop cancelled: device=%s", self.device_id)
                raise
            except Exception:  # noqa: BLE001
                self.session.decode_errors += 1
                log.exception("frame loop error: device=%s", self.device_id)
                await asyncio.sleep(1)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._source is not None:
            await self._source.aclose()
            self._source = None
        if self._room is not None:
            await self._room.disconnect()
            self._room = None
        self._started = False
        log.info("video_bridge stopped: device=%s", self.device_id)
