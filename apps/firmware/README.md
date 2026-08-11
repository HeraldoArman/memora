# Memora Firmware

Native ESP-IDF firmware for the Seeed Studio XIAO ESP32-S3 Sense.

## Build

Install ESP-IDF 5.4 or newer, activate its environment, then configure and build:

```bash
idf.py -C apps/firmware set-target esp32s3
idf.py -C apps/firmware menuconfig
idf.py -C apps/firmware build
idf.py -C apps/firmware flash monitor
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

The button is active-low with the internal pull-up enabled. The OV3660 camera and
onboard PDM microphone use the Sense expansion-board pins defined in `main/hardware.h`.

## Current scope

This first ESP-IDF increment initializes the board, Wi-Fi, OLED bus, button, power
telemetry, and LiveKit room/data transport. It publishes the backend-compatible
`device` telemetry topic and receives the backend `display` topic.

Camera and microphone media capture are isolated for the next increment: the LiveKit
SDK requires an `esp_capture` handle and H.264/Opus media pipeline, which must be
validated on the actual OV3660 and onboard PDM microphone hardware. There is no audio
renderer because the current hardware has no speaker.
