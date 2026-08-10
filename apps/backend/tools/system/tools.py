"""System tools — device telemetry (battery, network, info, firmware).

Pulled from the latest DeviceObservation in the current context. Firmware version is a
constant (no real firmware integration — firmware is out of scope).
"""

from __future__ import annotations

from tools.registry import ToolContext

_FIRMWARE_VERSION = "memora-backend-0.1.0"


async def battery_status(args: dict, ctx: ToolContext) -> dict:
    dev = ctx.device_snapshot()
    if not dev:
        return {"available": False}
    return {"battery_level": dev.get("battery_level"), "available": True}


async def network_status(args: dict, ctx: ToolContext) -> dict:
    dev = ctx.device_snapshot()
    if not dev:
        return {"available": False}
    return {"wifi_connected": dev.get("wifi_connected"), "available": True}


async def device_information(args: dict, ctx: ToolContext) -> dict:
    dev = ctx.device_snapshot()
    return {"device": dev or {}, "firmware": _FIRMWARE_VERSION}


async def firmware_version(args: dict, ctx: ToolContext) -> dict:
    return {"firmware_version": _FIRMWARE_VERSION}


SYSTEM_TOOL_FUNCS = {
    "battery_status": battery_status,
    "network_status": network_status,
    "device_information": device_information,
    "firmware_version": firmware_version,
}
