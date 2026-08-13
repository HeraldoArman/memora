# Video Bridge — ESP32 JPEG Ingest → Backend H.264

## Problem

The ESP32-S3 has no hardware H.264 encoder. The software encoder (`esp_h264` v1.3.7) saturates a CPU core at 320x240@1fps alongside WiFi, WebRTC, Opus audio, and camera capture. Scaling to 640x480 is impossible on this path.

## Solution

Move H.264 encoding off the ESP32 to the backend. The ESP32 captures JPEG (OV3660 on-sensor encoder, near-zero CPU cost) and POSTs raw JPEG frames to the backend via HTTP. The backend Video Bridge decodes JPEG and publishes H.264 to LiveKit via the Python SDK's `VideoSource`.

```
BEFORE:  ESP32 ── H.264 software encode ── WebRTC ──> LiveKit
AFTER:   ESP32 ── JPEG (sensor HW) ── HTTP ──> Backend ── H.264 ──> LiveKit
```

## Architecture

```
OV3660 ESP32-S3
    ↓ JPEG capture (1 FPS, 640x480, quality 12)
    ↓ HTTP POST (raw JPEG body)
Backend Video Bridge
    ↓ decode JPEG → RGB24 (cv2.imdecode)
    ↓ rtc.VideoSource.capture_frame()
    ↓ LiveKit SDK encodes H.264
LiveKit room
    ↓
Agent (face recognition + Gemini video)
Dashboard H.264 Debugger
```

ESP32 publishes **audio only** to LiveKit (Opus mic). Video goes through the bridge.

## Railway Deployment

The backend is deployed on Railway at:

```
https://backend-production-f5b2.up.railway.app
```

### ESP32 Configuration

Flash the firmware and configure via `idf.py menuconfig` → **Memora firmware**:

| Config                      | Value                                                                       |
| --------------------------- | --------------------------------------------------------------------------- |
| `MEMORA_INGEST_URL`         | `https://backend-production-f5b2.up.railway.app/api/media/video/frame`      |
| `MEMORA_TOKEN_URL`          | `https://<dashboard-domain>/api/token` (or backend if token route is there) |
| `MEMORA_LIVEKIT_SERVER_URL` | Your LiveKit server URL                                                     |
| `MEMORA_LIVEKIT_ROOM`       | `memora-test`                                                               |
| `MEMORA_LIVEKIT_IDENTITY`   | `memora-device`                                                             |
| `MEMORA_WIFI_SSID`          | Your WiFi                                                                   |
| `MEMORA_WIFI_PASSWORD`      | Your WiFi password                                                          |

### How it works end-to-end

1. ESP32 boots, connects to WiFi
2. ESP32 fetches a LiveKit token from `MEMORA_TOKEN_URL`
3. ESP32 joins LiveKit room (audio only — Opus mic)
4. ESP32 starts JPEG capture from OV3660 at 1 FPS
5. ESP32 POSTs each JPEG to `MEMORA_INGEST_URL` (raw binary, not base64)
6. Backend receives JPEG at `POST /api/media/video/frame`
7. On first frame, backend creates a `VideoBridge` that joins the same LiveKit room as `memora-video-bridge-<device_id>`
8. Bridge decodes JPEG → feeds `rtc.VideoSource.capture_frame()` → LiveKit SDK encodes H.264
9. Agent only processes video from `memora-video-bridge-*` identity (filtered in `entrypoint.py`)
10. Dashboard `/h264-debug` subscribes to the bridge's H.264 track

### Local development

For local dev, the ESP32 cannot use `localhost`. Point `MEMORA_INGEST_URL` to your machine's LAN IP:

```
http://192.168.1.xxx:8000/api/media/video/frame
```

The backend must listen on `0.0.0.0:8000` (already configured) and the firewall must allow port 8000.

## HTTP Ingest Protocol

### Request

```
POST /api/media/video/frame
Content-Type: image/jpeg
X-Memora-Device-ID: memora-device
X-Frame-ID: 123
X-Capture-Time-Ms: 1723456789000
X-Width: 640
X-Height: 480

<binary JPEG body>
```

### Response

```
202 Accepted
```

### Validation

- Max JPEG size: 300 KB
- Must start with `FF D8` and end with `FF D9`
- No base64 — raw binary only (saves ~33% bandwidth)
- No disk writes — frames are decoded in memory and discarded

## Backpressure

Queue maxsize=1 per device. If the encoder is busy:

- Old frame is discarded
- Newest frame is kept
- `dropped_frames` counter increments

At 1 FPS, the system never needs a buffer. A longer buffer only adds latency.

## Bridge Identity

The bridge joins LiveKit with identity `memora-video-bridge-<device_id>` and publishes one track:

- Track name: `camera-h264`
- Source: camera
- Codec: H.264
- Resolution: 640x480
- FPS: 1
- Bitrate: 300 kbps

The agent filters video tracks by `memora-video-bridge-` prefix to avoid processing duplicate tracks (e.g., if ESP accidentally publishes video).

## Token Security

- LiveKit API key/secret are never stored on the ESP32
- The ESP32 only has a token ingest URL and a token fetch URL
- The bridge generates its own LiveKit token server-side using the API key/secret

## Metrics

The bridge logs per-device:

- `received_frames` — total JPEG frames received
- `decoded_frames` — successfully decoded
- `published_frames` — pushed to VideoSource
- `dropped_frames` — dropped due to queue full
- `decode_errors` — failed JPEG decode
- `last_frame_age_ms` — time since last frame
- `average_jpeg_bytes` — mean JPEG size
- `average_decode_ms` — mean decode time

## Files

| File                                           | Role                           |
| ---------------------------------------------- | ------------------------------ |
| `apps/firmware/main/jpeg_ingest.cpp`           | ESP32 JPEG capture + HTTP POST |
| `apps/backend/api/routes/media.py`             | HTTP ingest endpoint           |
| `apps/backend/gateway/video_bridge/bridge.py`  | LiveKit H.264 publisher        |
| `apps/backend/gateway/video_bridge/session.py` | Per-device queue + metrics     |
| `apps/backend/gateway/livekit/entrypoint.py`   | Agent bridge identity filter   |

## Future

- WebSocket ingest for >5 FPS (avoids HTTP overhead per frame)
- Separate worker process for bridge (crash isolation from agent)
- Multiple device scaling (bridge registry → proper manager)
- Firmware build verification with ESP-IDF CI
