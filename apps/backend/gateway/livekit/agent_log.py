"""AgentLog — publish AI activity (tool calls, reasoning) to the web dashboard.

Mirror of Display, but for the dashboard's log pane instead of the OLED.
Publishes one JSON line per event on data-channel topic "agent_log" (reliable)
so a human can watch what the AI is trying to do. The dashboard subscribes to
that topic and renders each line.

Ponytail: plain JSON lines; the dashboard owns formatting.
"""

from __future__ import annotations

import json
import logging

from livekit import rtc

log = logging.getLogger(__name__)

_AGENT_LOG_TOPIC = "agent_log"
_MAX_PAYLOAD = 4000


class AgentLog:
    """Publishes {kind, text} events to the dashboard via room data channel."""

    def __init__(self, room: rtc.Room) -> None:
        self._room = room

    async def emit(self, kind: str, text: str) -> None:
        """Publish one event, truncated over _MAX_PAYLOAD. Kind is free-form."""
        if not text:
            return
        payload = json.dumps({"kind": kind, "text": text}, ensure_ascii=False)
        if len(payload) > _MAX_PAYLOAD:
            payload = payload[:_MAX_PAYLOAD]
        log.info("agent_log: kind=%s text=%r", kind, text[:200])
        await self._room.local_participant.publish_data(
            payload, reliable=True, topic=_AGENT_LOG_TOPIC
        )


# --- self-check: JSON round-trip ---
def _self_check() -> None:  # pragma: no cover
    import asyncio

    class _Room:
        class _lp:
            async def publish_data(self, payload, *, reliable, topic):
                assert reliable is True
                assert topic == _AGENT_LOG_TOPIC
                obj = json.loads(payload)
                assert obj == {"kind": "tool_call", "text": "hi"}

        local_participant = _lp()

    asyncio.run(AgentLog(_Room()).emit("tool_call", "hi"))
    print("agent_log self-check OK: publish + JSON round-trip")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
