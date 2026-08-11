"""Unit tests — device telemetry data channel (gateway/livekit/data_channel).

Pure parse function + topic-gated emit handler; no LiveKit connection needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from dto.observations import DeviceObservation
from gateway.livekit.data_channel import handle_data_received, parse_device_telemetry


class TestParseDeviceTelemetry:
    def test_valid_json(self) -> None:
        obs = parse_device_telemetry('{"battery_level": 72, "wifi_connected": true}')
        assert isinstance(obs, DeviceObservation)
        assert obs.battery_level == 72
        assert obs.wifi_connected is True
        assert obs.button_pressed is False  # default
        assert obs.confidence == 1.0

    def test_bytes_payload(self) -> None:
        obs = parse_device_telemetry(b'{"battery_level": 10, "button_pressed": true}')
        assert obs is not None
        assert obs.battery_level == 10
        assert obs.button_pressed is True

    def test_partial_payload_defaults(self) -> None:
        obs = parse_device_telemetry('{"unrelated": 1}')
        assert obs is not None
        assert obs.battery_level is None
        assert obs.wifi_connected is False

    def test_junk_rejected(self) -> None:
        assert parse_device_telemetry("not json") is None
        assert parse_device_telemetry(b"\xff\xfe") is None  # bad utf-8
        assert parse_device_telemetry("[]") is None  # not a dict
        assert parse_device_telemetry(None) is None  # TypeError path


class TestHandleDataReceived:
    async def test_wrong_topic_ignored(self) -> None:
        engine = AsyncMock()
        await handle_data_received("{}", "display", engine)
        engine.emit.assert_not_called()

    async def test_device_topic_emits(self) -> None:
        engine = AsyncMock()
        await handle_data_received('{"battery_level": 30}', "device", engine)
        engine.emit.assert_awaited_once()
        obs = engine.emit.await_args.args[0]
        assert isinstance(obs, DeviceObservation) and obs.battery_level == 30

    async def test_device_topic_junk_no_emit(self) -> None:
        engine = AsyncMock()
        await handle_data_received("garbage", "device", engine)
        engine.emit.assert_not_called()
