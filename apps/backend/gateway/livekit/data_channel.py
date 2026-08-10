"""Data channel — device telemetry in (button/battery/wifi) via room data messages.

The glasses publish DeviceObservation telemetry as a data message (topic "device"). We
parse it and emit a DeviceObservation into the ObservationEngine so it folds into the
CurrentContext (battery/wifi/button). The OLED out path is the Display (model text →
publish_data topic="display"); this module is the inbound half.

Ponytail: one handler function. The room.on("data_received") registration happens in the
entrypoint; this just parses + emits. Telemetry is JSON: {battery_level, wifi_connected,
button_pressed}. Missing fields default to None/false.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from dto.observations import DeviceObservation

log = logging.getLogger(__name__)

_DEVICE_TOPIC = "device"


def parse_device_telemetry(payload: bytes | str) -> DeviceObservation | None:
    """Parse a device data-message payload into a DeviceObservation.

    Returns None if the payload isn't valid device telemetry (wrong topic, bad JSON).
    Ponytail: tolerate missing fields — the glasses may send a partial telemetry packet.
    """
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return DeviceObservation(
        battery_level=data.get("battery_level"),
        wifi_connected=bool(data.get("wifi_connected", False)),
        button_pressed=bool(data.get("button_pressed", False)),
        confidence=1.0,  # device telemetry is authoritative
    )


async def handle_data_received(
    payload: bytes | str,
    topic: str | None,
    observation_engine: Any,
) -> None:
    """Room data_received handler → emit DeviceObservation if topic matches.

    Called by the entrypoint's @room.on("data_received") callback. Non-device topics are
    ignored (the display topic is outbound only).
    """
    if topic != _DEVICE_TOPIC:
        return
    obs = parse_device_telemetry(payload)
    if obs is None:
        log.debug("unparseable device telemetry: %r", payload)
        return
    await observation_engine.emit(obs)


# --- self-check: parse valid + reject junk ---
def _self_check() -> None:  # pragma: no cover
    # valid JSON
    obs = parse_device_telemetry('{"battery_level": 72, "wifi_connected": true}')
    assert obs is not None
    assert obs.battery_level == 72
    assert obs.wifi_connected is True
    assert obs.button_pressed is False  # default
    # bytes payload
    obs2 = parse_device_telemetry(b'{"battery_level": 10, "button_pressed": true}')
    assert obs2 is not None and obs2.button_pressed is True
    # junk → None
    assert parse_device_telemetry("not json") is None
    assert parse_device_telemetry(b"\xff\xfe") is None
    assert parse_device_telemetry('{"unrelated": 1}') is not None  # valid JSON, defaults
    print("data_channel self-check OK: valid parsed, junk rejected")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
