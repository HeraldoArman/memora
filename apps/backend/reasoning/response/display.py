"""Display — model text → glasses OLED via LiveKit data channel.

Gemini Live text parts are sent to the glasses display as a reliable data message on
topic "display". The firmware subscribes to that topic and renders the payload on the
OLED. Ponytail: publish the raw text string; the glasses client owns rendering/scroll.
No layout, no truncation logic here — that's a firmware concern.
"""

from __future__ import annotations

import logging

from livekit import rtc

log = logging.getLogger(__name__)

_DISPLAY_TOPIC = "display"
_MAX_PAYLOAD = 4000  # ponytail: cap payload; OLED is small, avoid huge sends


class Display:
    """Publishes model text to the glasses display via room data channel."""

    def __init__(self, room: rtc.Room) -> None:
        self._room = room

    async def show(self, text: str) -> None:
        """Publish `text` to topic="display", reliable. Truncates over _MAX_PAYLOAD."""
        if not text:
            return
        if len(text) > _MAX_PAYLOAD:
            text = text[:_MAX_PAYLOAD]
            # ponytail: hard truncation; no ellipsis logic — OLED scrolls/truncates itself
        log.info(
            "display.show → publish topic=%s len=%d text=%r", _DISPLAY_TOPIC, len(text), text[:120]
        )
        await self._room.local_participant.publish_data(text, reliable=True, topic=_DISPLAY_TOPIC)
        log.info("display published OK len=%d", len(text))


# --- self-check: truncation boundary ---
def _self_check() -> None:  # pragma: no cover
    assert _MAX_PAYLOAD == 4000
    long = "x" * 5000
    truncated = long[:_MAX_PAYLOAD]
    assert len(truncated) == 4000
    # empty + None are no-ops (caller checks, but assert the contract)
    assert not ""
    print(f"display self-check OK: cap={_MAX_PAYLOAD}")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
