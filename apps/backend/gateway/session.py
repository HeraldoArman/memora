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

    working_memory: WorkingMemory
    observation_engine: ObservationEngine
    tool_ctx: ToolContext
    # agent is wired last (create() builds the session first so the extraction hook can
    # reference the session's ConversationSession id).
    agent: ReasoningAgent | None = None
    # face repo shared by the track handler (identity lookup) + the agent's tools. Built
    # here (not lifespan) because the livekit-agent worker is a separate process.
    face_repo: Any = None
    # scene understander (Gemini Vision) for the video loop's scene path.
    scene_understander: Any = None
    # text embedder + index for semantic memory retrieval.
    text_embedder: Any = None
    text_index: Any = None
    # one ConversationSession per room — lazy-created on first extraction so episodic +
    # fact persistence have a session to hang on. None until the first turn consolidates.
    session_id: str | None = None
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

        from perception.scene.understander import SceneUnderstander

        scene_understander = SceneUnderstander()

        from vector.text_index import TextMemoryIndex

        from perception.embeddings.text_embeddings import TextEmbedder

        text_embedder = TextEmbedder()
        text_index = TextMemoryIndex.load(
            settings.faiss_index_path + ".text", dim=text_embedder.dim
        )

        from reasoning.planner.planner import ProactivePlanner

        planner = ProactivePlanner(
            reminder_service=tool_ctx.reminder_service,
            shopping_service=tool_ctx.shopping_service,
        )

        # wire observation engine → working memory
        obs_engine = ObservationEngine(working_memory)

        # build the session shell first so the extraction hook can reference its session_id.
        session = cls(
            working_memory=working_memory,
            observation_engine=obs_engine,
            tool_ctx=tool_ctx,
            face_repo=face_repo,
            scene_understander=scene_understander,
            text_embedder=text_embedder,
            text_index=text_index,
        )

        # extraction hook: consolidate each finished turn via the pipeline runner. Lazy
        # import to keep the module-level dep graph light (pipeline pulls DB services).
        # The ConversationSession is created lazily on the first turn (DB stays down-safe
        # for rooms that never speak).
        async def _on_extract(text: str) -> None:
            from pipeline.consolidator import Consolidator
            from pipeline.runner import PipelineRunner
            from services import MemoryService

            try:
                if session.session_id is None:
                    session.session_id = await MemoryService().start_session(
                        summary="device session"
                    )
                    log.info("conversation session created: %s", session.session_id)
                consolidator = Consolidator(
                    text_embedder=session.text_embedder,
                    text_index=session.text_index,
                )
                await PipelineRunner(consolidator=consolidator).run(
                    text, session_id=session.session_id
                )
            except Exception:  # noqa: BLE001 — extraction must not kill the room
                log.exception("pipeline run failed for turn")

        session.agent = ReasoningAgent(
            room=room,
            tool_ctx=tool_ctx,
            on_extract=_on_extract,
            planner=planner,
            text_embedder=text_embedder,
            text_index=text_index,
            # transcription → SpeechObservation → ObservationEngine (perception.md §10:
            # speech must reach CurrentContext so extraction sees the conversation).
            emit_observation=obs_engine.emit,
        )
        return session

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


# --- self-check: extraction hook lazily creates one ConversationSession + threads it ---
def _self_check() -> None:  # pragma: no cover
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    async def _run() -> None:
        room = MagicMock()
        session = RoomSession.create(room)
        assert session.session_id is None  # not created until first turn
        assert session.agent is not None and session.agent.on_extract is not None

        runs: list[dict] = []

        async def _fake_run(text, *, session_id=None):
            runs.append({"text": text, "session_id": session_id})
            return {"action": "create"}

        async def _start_session(*, summary=None):
            return "session-abc"

        with (
            patch(
                "services.MemoryService.start_session", new=AsyncMock(side_effect=_start_session)
            ),
            patch("pipeline.runner.PipelineRunner.run", new=AsyncMock(side_effect=_fake_run)),
        ):
            await session.agent.on_extract("Halo Asep")
            await session.agent.on_extract("Beli obat lagi")

        # one session created, both turns threaded with it
        assert session.session_id == "session-abc", session.session_id
        assert runs == [
            {"text": "Halo Asep", "session_id": "session-abc"},
            {"text": "Beli obat lagi", "session_id": "session-abc"},
        ], runs

    asyncio.run(_run())
    print("session self-check OK: one ConversationSession lazily created + threaded into pipeline")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
