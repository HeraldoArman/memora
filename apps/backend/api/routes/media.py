"""Media ingest endpoint — receives JPEG frames from ESP32 devices.

ESP32 captures JPEG from OV3660 and POSTs raw binary here. The Video Bridge
decodes and publishes as H.264 to LiveKit. No base64, no JSON wrapping —
raw JPEG body with metadata in headers.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from starlette.responses import Response

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/media", tags=["media"])

MAX_JPEG_SIZE = 300_000
JPEG_START = b"\xff\xd8"
JPEG_END = b"\xff\xd9"

# ponytail: single-device POC — bridge registry in module scope.
# Move to a proper manager when scaling to multiple devices.
_bridges: dict[str, object] = {}


async def _ensure_bridge(device_id: str, width: int, height: int) -> object:
    """Lazily create a VideoBridge for a device on first frame."""
    bridge = _bridges.get(device_id)
    if bridge is not None:
        return bridge

    from env import get_settings

    settings = get_settings()
    from gateway.video_bridge.bridge import VideoBridge

    bridge = VideoBridge(
        device_id=device_id,
        room_name="memora-test",
        width=width,
        height=height,
        livekit_url=settings.livekit_url,
        livekit_api_key=settings.livekit_api_key,
        livekit_api_secret=settings.livekit_api_secret,
    )
    await bridge.start()
    _bridges[device_id] = bridge
    log.info("video bridge created for device=%s", device_id)
    return bridge


@router.post("/video/frame")
async def ingest_frame(
    request: Request,
    x_memora_device_id: str = Header(..., alias="X-Memora-Device-ID"),
    x_frame_id: str = Header(..., alias="X-Frame-ID"),
    x_capture_time_ms: str = Header(..., alias="X-Capture-Time-Ms"),
    x_width: str = Header(..., alias="X-Width"),
    x_height: str = Header(..., alias="X-Height"),
) -> Response:
    body = await request.body()

    if len(body) > MAX_JPEG_SIZE:
        log.warning("jpeg too large: %d bytes from %s", len(body), x_memora_device_id)
        raise HTTPException(413, "JPEG too large")
    if len(body) < 2 or body[:2] != JPEG_START or body[-2:] != JPEG_END:
        log.warning("invalid JPEG markers from %s", x_memora_device_id)
        raise HTTPException(400, "Invalid JPEG")

    width = int(x_width)
    height = int(x_height)
    log.info(
        "jpeg received device=%s frame_id=%s bytes=%d %dx%d",
        x_memora_device_id,
        x_frame_id,
        len(body),
        width,
        height,
    )

    try:
        bridge = await _ensure_bridge(x_memora_device_id, width, height)
        bridge.push_frame(body)
    except Exception:  # noqa: BLE001
        log.exception("bridge push failed for %s", x_memora_device_id)

    return Response(status_code=202)


def register_bridge(device_id: str, bridge: object) -> None:
    _bridges[device_id] = bridge


def get_bridge(device_id: str) -> object | None:
    return _bridges.get(device_id)
