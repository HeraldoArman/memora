"""ReasoningAgent — owns the Gemini Live session + ContextEngine + tool wiring.

The agent is the per-room brain. It:
  - builds the ToolContext from the room's Working Memory (current_context set by the
    perception/gateway layer),
  - builds the initial context package via ContextEngine.build() and injects it into
    the system prompt at connect time (immutable thereafter),
  - wires the live session's callbacks: model text → Display, audio → Speaker,
    input transcription → Working Memory observation feed, turn_complete →
    pipeline extraction trigger (consolidate the just-finished turn into long-term
    memory),
  - exposes feed_video/feed_audio for the perception sampler/forwarder to push realtime
    input to Gemini.

Event-driven triggers (plan + reasoning_agent.md): reasoning fires on (a) user speech
turn boundary (turn_complete), (b) notable context change (new person visible), (c)
relevant reminder. Ponytail: for MVP we wire (a) the turn_complete → extraction, and
(b) context change handled by perception pushing a fresh video frame + the model's own
tool calls fetching current_scene. Explicit reminder-triggered proactive reasoning is
deferred to Phase 7 (planner).

No multi-user: one agent per room, one implicit device.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from context.engine import ContextEngine
from dto.observations import CurrentContext
from memory.retrieval.retriever import Retriever
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
        engine: ContextEngine | None = None,
        session: GeminiLiveSession | None = None,
        speaker: Speaker | None = None,
        display: Display | None = None,
        on_extract: Callable[[str], Any] | None = None,
        emit_observation: Callable[[object], Awaitable[None]] | None = None,
        planner=None,
        text_embedder=None,
        text_index=None,
    ) -> None:
        self.room = room
        self.ctx = tool_ctx
        self.engine = engine or ContextEngine(
            retriever=Retriever(text_embedder=text_embedder, text_index=text_index)
            if text_embedder is not None
            else None,
        )
        self.session = session or GeminiLiveSession()
        self.speaker = speaker or Speaker()
        self.display = display or Display(room)
        # on_extract(turn_text) — pipeline consolidation hook, set by gateway.
        self.on_extract = on_extract
        # emit_observation(obs) — observation feed (ObservationEngine.emit). Final speech
        # transcripts become SpeechObservations so extraction sees the conversation.
        self.emit_observation = emit_observation
        # proactive planner — periodic context-vs-reminder checker.
        self.planner = planner
        self._connected = False

    async def start(self, current: CurrentContext | None = None) -> None:
        """Build initial context, connect the live session, publish speaker, spawn receive.

        `current` is the latest Working Memory snapshot at agent start. The context
        package built from it seeds the system prompt; subsequent context flows via
        tool calls.
        """
        # 1. initial context package → system prompt
        self.ctx.current_context = current
        _, context_text = await self.engine.build(current)

        # 2. connect live session with tool surface + seeded prompt
        self.session.set_audio_sink(self.speaker.feed)
        self.session.set_turn_complete_callback(self._on_turn)
        await self.session.connect(
            ctx=self.ctx,
            context_text=context_text,
            on_text=self.display.show,
            on_transcription=self._on_transcription,
        )

        # 3. publish speaker track + start receive loop
        self.speaker.publish(self.room)
        self.session.start_receive()
        self._connected = True

        # 4. start proactive planner if wired
        if self.planner is not None:
            self.planner.start(self._get_context, self._on_proactive)
        log.info("reasoning agent started")

    async def _on_turn(self) -> None:
        """Turn boundary: trigger extraction/consolidation of the just-finished turn.

        The live session emits turn_complete after a model response finishes. We hand
        the latest speech (from Working Memory) to the pipeline consolidator via the
        on_extract hook. Ponytail: no turn-text accumulation here — the gateway/working
        memory owns the rolling transcript; we pass its latest entry.
        """
        if self.on_extract is None:
            return
        ctx = self.ctx.current_context
        speech = getattr(ctx, "speech", None) if ctx else None
        if speech:
            try:
                await self.on_extract(speech)
            except Exception:  # noqa: BLE001 — extraction failure must not kill agent
                log.exception("turn extraction hook failed")

    async def _on_transcription(self, text: str, is_final: bool) -> None:
        """Input speech transcription → observation feed (decision #3: continuous, not turn).

        Final transcripts are emitted as SpeechObservations into Working Memory via the
        emit_observation hook (set by the gateway to ObservationEngine.emit). Fuse only
        folds is_final=True into CurrentContext.speech, so interim is skipped to avoid
        noise. Extraction reads ctx.speech at turn boundaries — final-only is sufficient.
        """
        log.debug("transcription: %r (final=%s)", text, is_final)
        if not is_final or not text.strip():
            return
        if self.emit_observation is None:
            return
        from dto.observations import SpeechObservation

        try:
            await self.emit_observation(SpeechObservation(transcript=text, confidence=0.9))
        except Exception:  # noqa: BLE001 — observation failure must not kill the receive loop
            log.exception("emit speech observation failed")

    async def feed_video(self, jpeg: bytes) -> None:
        """Perception sampler pushes a frame here (≤1 FPS)."""
        await self.session.send_video(jpeg)

    async def feed_audio(self, pcm: bytes, *, sample_rate: int = 16000) -> None:
        """Perception speech forwarder pushes audio chunks here."""
        await self.session.send_audio(pcm, sample_rate=sample_rate)

    async def update_context(self, current: CurrentContext) -> None:
        """Working Memory pushes a fresh CurrentContext snapshot.

        The system prompt is immutable for the connection (arch decision #2), so we
        DON'T re-inject context. We just refresh the ToolContext so tool calls return
        fresh observation data (current_scene/visible_people read from this). If the
        context package itself must update, the agent reconnects the session.
        """
        self.ctx.current_context = current

    async def stop(self) -> None:
        if self.planner is not None:
            await self.planner.stop()
        if self._connected:
            await self.session.aclose()
            await self.speaker.aclose()
        self._connected = False
        log.info("reasoning agent stopped")

    def _get_context(self) -> CurrentContext | None:
        """Return the latest Working Memory snapshot for the planner."""
        return self.ctx.current_context

    async def _on_proactive(self, text: str) -> None:
        """Planner trigger → inject text into the live session."""
        try:
            await self.session.send_text(text)
            log.info("proactive prompt sent: %s", text[:80])
        except Exception:  # noqa: BLE001
            log.exception("proactive prompt failed")


# --- self-check: wiring (no live connection, no network) ---
def _self_check() -> None:  # pragma: no cover
    from unittest.mock import AsyncMock, MagicMock

    room = MagicMock()
    ctx = ToolContext()
    engine = MagicMock()
    engine.build = AsyncMock(return_value=(MagicMock(), "ctx text"))
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
    emitted: list = []
    emit_observation = AsyncMock(side_effect=lambda obs: emitted.append(obs))

    agent = ReasoningAgent(
        room=room,
        tool_ctx=ctx,
        engine=engine,
        session=session,
        speaker=speaker,
        display=display,
        emit_observation=emit_observation,
    )

    asyncio.run(agent.start(current=None))

    # context built + seeded into connect
    engine.build.assert_called_once()
    session.connect.assert_called_once()
    # speaker sink + turn cb wired
    session.set_audio_sink.assert_called_once_with(speaker.feed)
    session.set_turn_complete_callback.assert_called_once()
    # speaker published + receive started
    speaker.publish.assert_called_once_with(room)
    session.start_receive.assert_called_once()
    assert agent._connected

    # final transcription → SpeechObservation emitted; interim + empty skipped
    asyncio.run(agent._on_transcription("apa ini?", is_final=True))
    asyncio.run(agent._on_transcription("apa ini?", is_final=False))
    asyncio.run(agent._on_transcription("   ", is_final=True))
    assert len(emitted) == 1, emitted
    assert emitted[0].transcript == "apa ini?" and emitted[0].is_final
    assert type(emitted[0]).__name__ == "SpeechObservation"

    asyncio.run(agent.stop())
    assert not agent._connected
    print("agent self-check OK: context→connect→speaker→receive→speech-obs wiring verified")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
