"""ReasoningAgent — owns the Gemini Live session + tool wiring.

refactor/bare-minimum: stripped to Gemini Live + Speaker + Display + tool dispatch.
ContextEngine, Retriever, ProactivePlanner, on_extract, and emit_observation are
bypassed. Re-enable by passing them to the constructor again.

The agent is the per-room brain. It:
  - connects Gemini Live with the tool surface + static system prompt,
  - wires the live session's callbacks: output_transcription → Display, audio → Speaker,
  - exposes feed_prompt/feed_audio for the gateway to push user input.

No multi-user: one agent per room, one implicit device.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from reasoning.response.display import Display
from reasoning.response.speaker import Speaker
from reasoning.session.live_session import GeminiLiveSession
from tools import ToolContext

log = logging.getLogger(__name__)


class ReasoningAgent:
    """Per-room reasoning brain wiring perception → Gemini → response."""

    def __init__(
        self,
        *,
        room: Any,
        tool_ctx: ToolContext,
        session: GeminiLiveSession | None = None,
        speaker: Speaker | None = None,
        display: Display | None = None,
    ) -> None:
        self.room = room
        self.ctx = tool_ctx
        self.session = session or GeminiLiveSession()
        self.speaker = speaker or Speaker()
        self.display = display or Display(room)
        self._connected = False

    async def start(self, current: object = None) -> None:
        """Connect the live session, publish speaker, spawn receive loop.

        `current` is ignored in bare-minimum — system prompt is static.
        """
        # connect live session (non-blocking — background task with retry)
        self.session.set_audio_sink(self.speaker.feed)
        self.session.set_turn_complete_callback(self._on_turn)
        await self.session.connect(
            ctx=self.ctx,
            context_text="",  # bare-minimum: static system prompt, no context package
            on_text=self.display.show,
            on_transcription=self._on_transcription,
        )

        # publish speaker track + start receive loop (waits for connect in background)
        self.speaker.publish(self.room)
        self.session.start_receive()
        self._connected = True
        log.info("reasoning agent started")

    async def _on_turn(self) -> None:
        """Turn boundary — no extraction in bare-minimum."""
        pass

    async def _on_transcription(self, text: str, is_final: bool) -> None:
        """Input speech transcription — no observation feed in bare-minimum."""
        log.debug("transcription: %r (final=%s)", text, is_final)

    async def feed_prompt(self, text: str) -> None:
        """Inject a text prompt into the live session (from dashboard "prompt" topic)."""
        log.info("feeding prompt to gemini: %r", text[:120])
        await self.session.send_text(text)

    async def feed_audio(self, pcm: bytes, *, sample_rate: int = 16000) -> None:
        """Perception speech forwarder pushes audio chunks here."""
        await self.session.send_audio(pcm, sample_rate=sample_rate)

    async def stop(self) -> None:
        if self._connected:
            await self.session.aclose()
            await self.speaker.aclose()
        self._connected = False
        log.info("reasoning agent stopped")


# --- self-check: wiring (no live connection, no network) ---
def _self_check() -> None:  # pragma: no cover
    from unittest.mock import AsyncMock, MagicMock

    room = MagicMock()
    ctx = ToolContext()
    session = MagicMock()
    session.connect = AsyncMock()
    session.aclose = AsyncMock()
    session.start_receive = MagicMock()
    session.set_audio_sink = MagicMock()
    session.set_turn_complete_callback = MagicMock()
    speaker = MagicMock()
    speaker.publish = MagicMock()
    speaker.aclose = AsyncMock()
    display = MagicMock()
    display.show = AsyncMock()

    agent = ReasoningAgent(
        room=room,
        tool_ctx=ctx,
        session=session,
        speaker=speaker,
        display=display,
    )

    asyncio.run(agent.start(current=None))

    session.connect.assert_called_once()
    session.set_audio_sink.assert_called_once_with(speaker.feed)
    session.set_turn_complete_callback.assert_called_once()
    speaker.publish.assert_called_once_with(room)
    session.start_receive.assert_called_once()
    assert agent._connected

    asyncio.run(agent.stop())
    assert not agent._connected
    print("agent self-check OK: connect→speaker→receive wiring verified")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
