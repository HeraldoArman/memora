"""Per-room session state — bundles the agent + perception + working memory.

One RoomSession per LiveKit room. The entrypoint creates this on job start and tears it
down on job end. It owns:
  - WorkingMemory (latest CurrentContext, 30s TTL),
  - ObservationEngine (single write path to WorkingMemory),
  - ToolContext (services + current_context, shared by the agent + tools),
  - ReasoningAgent (Gemini Live + ContextEngine + Speaker + Display).

Ponytail: a plain dataclass-ish holder, not a state machine. The entrypoint drives the
lifecycle; this just groups the collaborators so they share one WorkingMemory + ToolContext.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from perception.observation.engine import ObservationEngine
from perception.observation.working_memory import WorkingMemory
from reasoning.agent.agent import ReasoningAgent
from tools import ToolContext

log = logging.getLogger(__name__)


@dataclass
class RoomSession:
    """All state for one LiveKit room (one implicit device, no multi-user)."""

    agent: ReasoningAgent
    working_memory: WorkingMemory
    observation_engine: ObservationEngine
    tool_ctx: ToolContext
    # face repo shared by the track handler (identity lookup) + the agent's tools. Built
    # here (not lifespan) because the livekit-agent worker is a separate process.
    face_repo: Any = None
    # background tasks spawned by track handlers (video loop, audio loop), for cleanup
    tasks: list = field(default_factory=list)

    @classmethod
    def create(cls, room) -> RoomSession:
        """Build a wired RoomSession for a connected LiveKit room.

        The agent's ToolContext.current_context is kept in sync with WorkingMemory by the
        gateway: whenever the observation engine writes a new CurrentContext, the gateway
        pushes it to both WorkingMemory (via the engine) and the tool_ctx (so tools see it).
        """
        from env import get_settings
        from vector.repository import FaceRepository

        settings = get_settings()
        working_memory = WorkingMemory()
        tool_ctx = ToolContext()
        # face repo for THIS process (FastAPI lifespan only wires the API process; the
        # livekit-agent worker never runs it). Loads index + sidecar, or starts empty.
        face_repo = FaceRepository.load(
            settings.faiss_index_path,
            known_threshold=settings.face_match_threshold,
            possible_threshold=settings.face_possible_match_threshold,
        )
        tool_ctx.face_repo = face_repo  # wires PersonService so search_by_face/register_face work
        log.info("room session face repo ready: %d embedding(s)", face_repo.size)

        # wire observation engine → working memory
        obs_engine = ObservationEngine(working_memory)

        # extraction hook: consolidate each finished turn via the pipeline runner.
        # Lazy import to keep the module-level dep graph light (pipeline pulls DB services).
        async def _on_extract(text: str) -> None:
            from pipeline.runner import PipelineRunner

            try:
                await PipelineRunner().run(text)
            except Exception:  # noqa: BLE001 — extraction must not kill the room
                log.exception("pipeline run failed for turn")

        agent = ReasoningAgent(
            room=room,
            tool_ctx=tool_ctx,
            on_extract=_on_extract,
            # transcription → SpeechObservation → ObservationEngine (perception.md §10:
            # speech must reach CurrentContext so extraction sees the conversation).
            emit_observation=obs_engine.emit,
        )
        return cls(
            agent=agent,
            working_memory=working_memory,
            observation_engine=obs_engine,
            tool_ctx=tool_ctx,
            face_repo=face_repo,
        )

    async def start(self) -> None:
        """Start observation engine + reasoning agent with the latest context (if any)."""
        self.observation_engine.start()
        await self.agent.start(current=self.working_memory.get())
        log.info("room session started")

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        await self.observation_engine.stop()
        await self.agent.stop()
        log.info("room session stopped")

    def sync_context(self) -> None:
        """Push the latest WorkingMemory snapshot into the ToolContext (tools see fresh data)."""
        self.tool_ctx.current_context = self.working_memory.get()
