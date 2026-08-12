"""Per-room session state — bundles the agent + face repo + tool context.

refactor/bare-minimum: stripped to 4 components — Gemini Live, InsightFace, Neo4j,
Postgres. ObservationEngine, WorkingMemory, ContextEngine, ProactivePlanner,
SceneUnderstander, TextEmbedder, TextIndex, and Consolidator are bypassed (not
deleted — re-enable by wiring them back in create() + start()).

One RoomSession per LiveKit room. The entrypoint creates this on job start and tears it
down on job end.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from reasoning.agent.agent import ReasoningAgent
from tools import ToolContext

log = logging.getLogger(__name__)


@dataclass
class RoomSession:
    """All state for one LiveKit room (one implicit device, no multi-user)."""

    tool_ctx: ToolContext
    agent: ReasoningAgent | None = None
    face_repo: Any = None
    # background tasks spawned by track handlers (video loop, audio loop), for cleanup
    tasks: list = field(default_factory=list)

    @classmethod
    async def create(cls, room) -> RoomSession:
        """Build a wired RoomSession for a connected LiveKit room."""
        from env import get_settings
        from vector.repository import FaceRepository

        settings = get_settings()
        # face repo for THIS process — rebuilt from Postgres (durable store) so both
        # backend + worker share face registrations without a shared volume.
        face_repo = await FaceRepository.from_db(
            known_threshold=settings.face_match_threshold,
            possible_threshold=settings.face_possible_match_threshold,
            dim=settings.face_embedding_dim,
        )
        tool_ctx = ToolContext(face_repo=face_repo)

        # Step 1: lazily create a conversation session for episodic memory + fact linking.
        session_id = None
        try:
            from services import MemoryService

            session_id = await MemoryService().start_session(summary="livekit room")
            tool_ctx.session_id = session_id
            log.info("conversation session started: %s", session_id)
        except Exception:  # noqa: BLE001 — DB down → extraction still runs, no episodic record
            log.warning("conversation session start failed; episodic memory unavailable")

        log.info("room session face repo ready: %d embedding(s)", face_repo.size)

        # ponytail: insightface loads ~9s of ONNX models — fire-and-forget in a thread
        # so the event loop isn't blocked. If the model isn't available yet when the
        # first video frame arrives, _load_app() runs lazily on that call (same singleton).
        import asyncio as _aio

        from perception.face.recognizer import preload as preload_face

        _aio.get_event_loop().run_in_executor(None, preload_face)

        # Step 1: wire extraction pipeline as the on_extract callback.
        async def _on_extract(text: str, sid: str | None) -> None:
            from pipeline.runner import PipelineRunner

            await PipelineRunner().run(text, session_id=sid)

        session = cls(
            tool_ctx=tool_ctx,
            face_repo=face_repo,
        )
        session.agent = ReasoningAgent(
            room=room,
            tool_ctx=tool_ctx,
            on_extract=_on_extract,
        )
        return session

    async def start(self) -> None:
        """Start reasoning agent with static context (no observation engine)."""
        await self.agent.start(current=None)
        log.info("room session started")

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        await self.agent.stop()
        log.info("room session stopped")


# --- self-check: RoomSession.create wires face_repo + agent ---
def _self_check() -> None:  # pragma: no cover
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from vector.index import FaceIndex
    from vector.repository import FaceRepository

    async def _run() -> None:
        room = MagicMock()
        fake_repo = FaceRepository(FaceIndex(dim=8))
        with patch(
            "vector.repository.FaceRepository.from_db",
            new=AsyncMock(return_value=fake_repo),
        ):
            session = await RoomSession.create(room)
        assert session.face_repo is not None
        assert session.tool_ctx.face_repo is not None
        assert session.agent is not None
        assert session.tool_ctx.last_face is None  # no face detected yet

    asyncio.run(_run())
    print("session self-check OK: face_repo + agent wired, last_face=None")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
