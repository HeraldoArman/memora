"""LiveKit agent entrypoint — AgentSession + Gemini RealtimeModel.

Replaces the custom GeminiLiveSession plumbing with LiveKit's AgentSession +
google.realtime.RealtimeModel. Audio, video, reconnection, VAD-based turn
detection, and audio output are handled by the framework.

InsightFace runs in parallel via track_handler for face recognition →
tool_ctx.last_face. Video is NOT sent to Gemini (context window exhaustion);
face/scene data reaches the model via tool_ctx.
"""

from __future__ import annotations

import asyncio
import logging

from livekit import rtc
from livekit.agents import AgentSession, JobContext, room_io
from livekit.agents.llm import ChatMessage

from gateway.livekit.track_handler import handle_video_track
from reasoning.agent.agent import MemoraAgent
from reasoning.response.display import Display
from tools import ToolContext

log = logging.getLogger(__name__)

BRIDGE_IDENTITY_PREFIX = "memora-video-bridge-"


async def entrypoint(ctx: JobContext) -> None:
    """Per-room job: build AgentSession with Gemini RealtimeModel."""
    room = ctx.room
    log.info("entrypoint started for room %s", room.name)

    # --- Wire stores (Postgres + Neo4j) ---
    log.info("initializing stores (postgres + neo4j)...")
    await _init_stores()
    log.info("stores initialized")

    # --- Connect to room ---
    log.info("connecting to room %s...", room.name)
    await ctx.connect(auto_subscribe=True)
    log.info(
        "job connected to room %s (participants=%d)",
        room.name,
        len(room.remote_participants),
    )
    for p in room.remote_participants.values():
        log.info("  participant: %s (tracks=%d)", p.identity, len(p.track_publications))

    # --- Build tool context ---
    from env import get_settings
    from vector.repository import FaceRepository

    settings = get_settings()
    log.info(
        "building face repo: dim=%d known_threshold=%.2f possible_threshold=%.2f",
        settings.face_embedding_dim,
        settings.face_match_threshold,
        settings.face_possible_match_threshold,
    )
    face_repo = await FaceRepository.from_db(
        known_threshold=settings.face_match_threshold,
        possible_threshold=settings.face_possible_match_threshold,
        dim=settings.face_embedding_dim,
    )
    log.info("face repo loaded: %d embedding(s)", face_repo.size)

    tool_ctx = ToolContext(face_repo=face_repo)
    log.info("tool context built (face_repo=%d embeddings)", face_repo.size)

    # --- Start conversation session for episodic memory ---
    session_id = None
    try:
        from services import MemoryService

        log.info("starting conversation session for episodic memory...")
        session_id = await MemoryService().start_session(summary="livekit room")
        tool_ctx.session_id = session_id
        log.info("conversation session started: %s", session_id)
    except Exception:  # noqa: BLE001
        log.warning("conversation session start failed; episodic memory unavailable", exc_info=True)

    # --- Preload InsightFace in background ---
    log.info("preloading InsightFace models in background thread...")
    from perception.face.recognizer import preload as preload_face

    asyncio.get_event_loop().run_in_executor(None, preload_face)

    # --- Scene understander (Step 3) ---
    from perception.scene.understander import SceneUnderstander

    scene_understander = SceneUnderstander()
    log.info("scene understander created")

    # --- Observation engine + working memory (Step 5) ---
    from perception.observation.engine import ObservationEngine
    from perception.observation.working_memory import WorkingMemory

    working_memory = WorkingMemory()
    obs_engine = ObservationEngine(working_memory)
    tool_ctx.working_memory = working_memory
    log.info("observation engine + working memory created")

    # --- Wire extraction pipeline (with text embeddings for semantic retrieval) ---
    from memory.retrieval.retriever import Retriever
    from perception.embeddings.text_embeddings import TextEmbedder

    text_embedder = TextEmbedder()

    from vector.text_index import TextMemoryIndex

    text_index = TextMemoryIndex(dim=768)

    async def _on_extract(text: str, sid: str | None) -> None:
        log.info("on_extract triggered: text=%r sid=%s", text[:200], sid)
        try:
            from pipeline.runner import PipelineRunner

            await PipelineRunner(text_embedder=text_embedder, text_index=text_index).run(
                text, session_id=sid
            )
            log.info("extraction pipeline completed")
        except Exception:  # noqa: BLE001
            log.warning("extraction failed: %s", exc_info=True)

    # --- Create display ---
    display = Display(room)
    log.info("display wired to room %s", room.name)

    # --- Create agent-log publisher (dashboard log pane) ---
    from gateway.livekit.agent_log import AgentLog

    agent_log = AgentLog(room)
    log.info("agent log wired to room %s", room.name)

    # --- Create context engine for semantic memory retrieval ---
    from context.engine import ContextEngine

    retriever = Retriever(text_embedder=text_embedder, text_index=text_index)
    context_engine = ContextEngine(retriever=retriever)
    log.info("context engine created (retriever with text embedder + index)")

    # --- Create proactive planner (Step 4) ---
    from reasoning.planner.planner import ProactivePlanner

    planner = ProactivePlanner(
        reminder_service=tool_ctx.reminder_service,
        shopping_service=tool_ctx.shopping_service,
        text_embedder=text_embedder,
    )
    log.info("proactive planner created")

    # --- Create agent ---
    log.info(
        "creating MemoraAgent (%d tool declarations)...",
        len(__import__("schemas").ALL_FUNCTION_DECLARATIONS),
    )
    agent = MemoraAgent(
        tool_ctx=tool_ctx,
        on_extract=_on_extract,
        context_engine=context_engine,
        planner=planner,
        on_log=agent_log.emit,
    )
    log.info("MemoraAgent created")

    # --- Create AgentSession (LLM is on the Agent, matching tuntun-in) ---
    log.info("creating AgentSession")
    session = AgentSession()
    log.info("AgentSession created")

    # --- Wire speech observations via user_input_transcribed ---
    @session.on("user_input_transcribed")
    def _on_transcribed(ev):
        if not ev.is_final or not ev.transcript.strip():
            return
        from dto.observations import SpeechObservation

        asyncio.create_task(agent_log.emit("user", ev.transcript.strip()))
        asyncio.create_task(
            obs_engine.emit(
                SpeechObservation(transcript=ev.transcript, is_final=True, confidence=0.95)
            )
        )

    # --- Wire display + extraction + context refresh via conversation_item_added ---
    _user_turn_count = 0
    _CONTEXT_REFRESH_INTERVAL = 5

    @session.on("conversation_item_added")
    def _on_conversation_item(ev):
        nonlocal _user_turn_count
        try:
            item = ev.item
            if not isinstance(item, ChatMessage):
                log.debug(
                    "conversation_item_added: non-ChatMessage item type=%s", type(item).__name__
                )
                return
            log.info(
                "conversation_item_added: role=%s text=%r interrupted=%s",
                item.role,
                (item.text_content or "")[:200],
                item.interrupted,
            )
            if item.role == "assistant":
                text = item.text_content or ""
                if text:
                    log.info("display.show → publishing %d chars to topic=display", len(text))
                    asyncio.create_task(display.show(text))
                    asyncio.create_task(agent_log.emit("assistant", text))
                else:
                    log.debug("assistant message has no text content, skipping display")
            # Extraction + periodic context refresh: fire on user messages (turn boundary)
            if item.role == "user":
                text = item.text_content or ""
                if text:
                    log.info("user turn detected, triggering extraction: %r", text[:200])
                    asyncio.create_task(_on_extract(text, session_id))
                    _user_turn_count += 1
                    if _user_turn_count % _CONTEXT_REFRESH_INTERVAL == 0:
                        log.info("turn %d → refreshing context", _user_turn_count)
                        asyncio.create_task(agent._refresh_context())
                else:
                    log.debug("user message has no text content, skipping extraction")
        except Exception:  # noqa: BLE001
            log.debug("conversation_item_added parse failed", exc_info=True)

    # --- Wire track handlers for InsightFace (video only) ---
    @room.on("track_subscribed")
    def _on_track(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        log.info(
            "track SUBSCRIBED: kind=%s source=%s sid=%s from %s",
            publication.kind,
            publication.source,
            publication.sid,
            participant.identity,
        )
        if publication.kind == rtc.TrackKind.KIND_VIDEO:
            if participant.identity.startswith(BRIDGE_IDENTITY_PREFIX):
                log.info(
                    "spawning video loop for InsightFace (track from bridge %s)",
                    participant.identity,
                )
                asyncio.create_task(
                    handle_video_track(track, room, tool_ctx, scene_understander, obs_engine)
                )
            else:
                log.info("ignoring video track from non-bridge %s", participant.identity)
        elif publication.kind == rtc.TrackKind.KIND_AUDIO:
            log.info(
                "audio track subscribed from %s — AgentSession handles audio input automatically",
                participant.identity,
            )

    @room.on("track_published")
    def _on_track_pub(pub: rtc.RemoteTrackPublication, p: rtc.RemoteParticipant):
        log.info(
            "track published: sid=%s kind=%s source=%s from %s — subscribing",
            pub.sid,
            pub.kind,
            pub.source,
            p.identity,
        )
        pub.set_subscribed(True)

    @room.on("participant_connected")
    def _on_participant(p: rtc.RemoteParticipant):
        log.info("participant connected: %s (tracks=%d)", p.identity, len(p.track_publications))

    @room.on("track_subscription_failed")
    def _on_track_fail(p: rtc.RemoteParticipant, sid: str, error: str):
        log.error("track subscription FAILED: sid=%s from %s error=%s", sid, p.identity, error)

    # Subscribe to existing participant tracks
    for p in room.remote_participants.values():
        log.info(
            "checking existing participant: %s (tracks=%d)", p.identity, len(p.track_publications)
        )
        for pub in p.track_publications.values():
            if not pub.subscribed:
                log.info("subscribing to existing track: sid=%s kind=%s", pub.sid, pub.kind)
                pub.set_subscribed(True)
            if pub.subscribed and pub.track and pub.kind == rtc.TrackKind.KIND_VIDEO:
                if p.identity.startswith(BRIDGE_IDENTITY_PREFIX):
                    log.info(
                        "spawning video loop for existing video track from bridge %s", p.identity
                    )
                    asyncio.create_task(
                        handle_video_track(
                            pub.track, room, tool_ctx, scene_understander, obs_engine
                        )
                    )
                else:
                    log.info("ignoring existing video track from non-bridge %s", p.identity)

    # --- Wire data channel for text prompts ---
    @room.on("data_received")
    def _on_data(packet: rtc.DataPacket):
        topic = packet.topic or ""
        data = bytes(packet.data)
        log.info("data_received: topic=%r len=%d from=%s", topic, len(data), packet.participant)
        if topic == "prompt":
            text = data.decode("utf-8", errors="replace")
            log.info(
                "prompt received: %r — generating reply via session.generate_reply", text[:200]
            )
            asyncio.create_task(agent_log.emit("user", f"[prompt] {text}"))
            # Fire extraction so prompt turns persist like spoken turns: graph edges,
            # memory_facts, and the episodic user message. generate_reply fires the
            # assistant reply + display but creates no user-role conversation_item_added,
            # so without this the prompt path skips the whole extraction pipeline.
            asyncio.create_task(_on_extract(text, session_id))
            try:
                session.generate_reply(instructions=text)
            except RuntimeError:
                log.warning("prompt received but AgentSession not running; dropping")
        elif topic == "device":
            from gateway.livekit.data_channel import handle_data_received

            asyncio.create_task(handle_data_received(data, topic, obs_engine))
        else:
            log.debug("unknown data topic: %r len=%d", topic, len(data))

    # --- Start the session ---
    log.info(
        "starting AgentSession with RoomOptions(video_input=True, audio_input=True, audio_output=True)..."
    )
    await session.start(
        room=room,
        agent=agent,
        room_options=room_io.RoomOptions(
            video_input=True,
            audio_input=True,
            audio_output=True,
        ),
    )
    log.info("agent session started — agent is now listening and seeing video")

    obs_engine.start()
    log.info("observation engine started")

    # --- Wait until the job ends ---
    log.info("entrypoint setup complete, waiting for job to end (room=%s)", room.name)
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        log.info("job cancelled for room %s", room.name)
    finally:
        log.info("closing AgentSession for room %s...", room.name)
        await planner.stop()
        log.info("proactive planner stopped")
        await obs_engine.stop()
        log.info("observation engine stopped")
        await session.aclose()
        log.info("room session torn down for %s", room.name)


async def _init_stores() -> None:
    """Wire Postgres + Neo4j for this worker process."""
    from env import get_settings
    from graph import client as neo4j_client

    from postgres import session as pg_session

    settings = get_settings()
    log.info(
        "init stores: database_url=%s neo4j_uri=%s",
        settings.database_url[:50] + "..."
        if len(settings.database_url) > 50
        else settings.database_url,
        settings.neo4j_uri,
    )
    try:
        pg_session.init_engine(settings.database_url)
        log.info("postgres engine initialized")
    except Exception:  # noqa: BLE001
        log.exception("postgres init failed; memory persistence unavailable")
    try:
        await neo4j_client.init_driver(
            settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password
        )
        log.info("neo4j driver initialized")
    except Exception:  # noqa: BLE001
        log.exception("neo4j init failed; graph + face-name lookup unavailable")


# --- self-check: entrypoint is an awaitable JobContext handler ---
def _self_check() -> None:  # pragma: no cover
    import inspect

    assert callable(entrypoint)
    assert inspect.iscoroutinefunction(entrypoint), "entrypoint must be async"
    print("entrypoint self-check OK: async entrypoint(ctx: JobContext) ready for rtc_session")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
