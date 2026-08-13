# Memora Firmware

Native ESP-IDF firmware for the Seeed Studio XIAO ESP32-S3 Sense.

## Build

Install ESP-IDF 5.4 or newer, activate its environment, then configure and build:

```bash
idf.py -C apps/firmware set-target esp32s3
idf.py -C apps/firmware menuconfig
idf.py -C apps/firmware build
idf.py -C apps/firmware -p COM10 flash monitor
```

The LiveKit ESP32 SDK is pinned to `0.3.10` in `main/idf_component.yml`.

## Hardware wiring

| Device | XIAO pin |
| --- | --- |
| OLED VCC | 3V3 |
| OLED GND | GND |
| OLED SDA | D4 / GPIO5 |
| OLED SCL | D5 / GPIO6 |
| Button leg 1 | D1 / GPIO2 |
| Button leg 2 | GND |

The button is no longer required for boot or connection. The firmware connects to Wi-Fi,
requests a LiveKit token from the dashboard, joins the room, and starts the microphone and
JPEG ingest automatically. The OV3660 camera and onboard PDM microphone use the
Sense expansion-board pins defined in `main/hardware.h`.

The OLED uses I2C1 because the camera SCCB bus uses I2C0 internally. It renders incoming
`display` data messages directly with a native 5x7 font, wrapping long responses across
the 128x64 screen. IDF logs include Wi-Fi/LiveKit state, media startup, microphone levels,
data-channel payloads, and OLED output.

## Current scope

This first ESP-IDF increment initializes the board, Wi-Fi, OLED bus, power telemetry,
and LiveKit room/data transport. It publishes the backend-compatible
`device` telemetry topic and receives the backend `display` topic.

The firmware captures OV3660 frames as JPEG at 1024x768 (XGA), 1 FPS, and posts them as raw
`image/jpeg` bodies to the backend video ingest endpoint. The backend decodes those JPEG
frames and publishes the H.264 LiveKit track. The onboard PDM microphone remains an Opus
mono track at 16 kHz. There is no audio renderer because the current hardware has no speaker.

## Local development connection

The ESP cannot use `localhost` to reach the developer computer. Set
`MEMORA_TOKEN_URL` and `MEMORA_INGEST_URL` in `idf.py menuconfig` to the computer's LAN IPv4
address, for example:

```text
http://192.168.1.42:3000/api/token
http://192.168.1.42:8000/api/media/video/frame
```

## Railway production connection

Fresh firmware configurations default to the deployed Memora services:

```text
https://dashboard-production-43b8.up.railway.app/api/token
https://backend-production-f5b2.up.railway.app/api/media/video/frame
```

The firmware validates the Railway HTTPS certificates with ESP-IDF's bundled CA
certificates. Existing `sdkconfig` values take precedence over these defaults, so run
`idf.py -C apps/firmware menuconfig` and update both URLs when reusing an older local
configuration. Wi-Fi credentials remain device-local menuconfig values and are not part
of the repository configuration.

The dashboard token route creates the room token and explicitly dispatches the backend
worker using `AGENT_NAME`. Set the same `AGENT_NAME` value in the backend environment and
the dashboard environment; this value stays server-side and does not need to be stored in
the firmware. The returned LiveKit `server_url` is then used by the ESP, so the ESP does
not need the LiveKit API secret. Start the local services with Docker Compose and
`bun run dev`, and allow TCP port 3000 through the host firewall. The dashboard dev server
is configured to listen on `0.0.0.0` for this LAN access.

The backend's video bridge receives the JPEG body, decodes it, and publishes H.264 to
LiveKit. The backend's Gemini `AgentSession` and worker then consume the LiveKit audio/video
track. The worker samples video at its configured `frame_sample_fps` (currently 0.5 FPS),
so the firmware's 1 FPS JPEG upload provides fresh frames without requiring an ESP-side
H.264 encoder.

If token HTTP is not available, a pre-generated token can be configured with
`MEMORA_LIVEKIT_SERVER_URL` and `MEMORA_LIVEKIT_TOKEN` as a fallback.
