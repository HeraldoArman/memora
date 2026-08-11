"""LiveKit agent entrypoint — the per-room job handler.

Registered via AgentServer.rtc_session(entrypoint, agent_name=...) in workers/livekit_worker.py.
The framework calls entrypoint(ctx: JobContext) when a room is assigned. We:
  1. ctx.connect(auto_subscribe=True) — join the room, auto-subscribe to participant tracks.
  2. Build a RoomSession (agent + perception + working memory).
  3. Start the session (observation engine + reasoning agent connect to Gemini Live).
  4. Wire @room.on("track_subscribed") → track_handler (spawn video + audio loops).
  5. Wire @room.on("data_received") → data_channel (device telemetry in).
  6. On job end / participant disconnect → stop the session (cancels loops, closes Gemini).

Ponytail: one entrypoint function. No reconnection logic here — livekit-agents handles
job re-dispatch; Phase 7 adds graceful Gemini reconnect within a room.

No multi-user: one room = one implicit device = one RoomSession.
"""

from __future__ import annotations

import asyncio
import logging

from livekit import rtc
from livekit.agents import JobContext

from gateway.livekit.data_channel import handle_data_received
from gateway.livekit.track_handler import handle_audio_track, handle_video_track
from gateway.session import RoomSession

log = logging.getLogger(__name__)


async def entrypoint(ctx: JobContext) -> None:
    """Per-room job: build session, wire handlers, connect, run until closed."""
    room = ctx.room

    # The worker is a separate process — it never runs the FastAPI lifespan, so Postgres +
    # Neo4j are wired here before any session/turn touches them (extraction, face names).
    await _init_stores()

    # Connect to the room FIRST so we don't miss early prompts/tracks while
    # RoomSession.create() loads models (~9s insightface). The session is built
    # after connect; track handlers are wired in start() below.
    await ctx.connect(auto_subscribe=True)
    log.info("job connected to room %s (participants=%d)", room.name, len(room.remote_participants))

    session = await RoomSession.create(room)

    @room.on("participant_connected")
    def _on_participant(p: rtc.RemoteParticipant):
        log.info("participant connected: %s (tracks=%d)", p.identity, len(p.track_publications))

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

    @room.on("track_subscribed")
    def _on_track(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        kind = publication.kind
        log.info(
            "track SUBSCRIBED: kind=%s source=%s from %s",
            kind,
            publication.source,
            participant.identity,
        )
        if kind == rtc.TrackKind.KIND_VIDEO:
            task = asyncio.create_task(handle_video_track(track, room, session))
            session.tasks.append(task)
            log.info("video track subscribed from %s", participant.identity)
        elif kind == rtc.TrackKind.KIND_AUDIO:
            task = asyncio.create_task(handle_audio_track(track, room, session))
            session.tasks.append(task)
            log.info("audio track subscribed from %s", participant.identity)

    @room.on("track_subscription_failed")
    def _on_track_fail(p: rtc.RemoteParticipant, sid: str, error: str):
        log.error("track subscription FAILED: sid=%s from %s error=%s", sid, p.identity, error)

    @room.on("data_received")
    def _on_data(packet: rtc.DataPacket):
        topic = packet.topic or ""
        data = bytes(packet.data)
        log.info("data_received: topic=%r len=%d", topic, len(data))
        if topic == "prompt":
            text = data.decode("utf-8", errors="replace")
            log.info("prompt received: %r — feeding to gemini", text)
            asyncio.create_task(session.agent.feed_prompt(text))
        else:
            asyncio.create_task(handle_data_received(data, topic, session.observation_engine))

    # explicitly subscribe to any tracks from participants already in the room
    for p in room.remote_participants.values():
        log.info("existing participant: %s (tracks=%d)", p.identity, len(p.track_publications))
        for pub in p.track_publications.values():
            if not pub.subscribed:
                log.info("subscribing to existing track: sid=%s kind=%s", pub.sid, pub.kind)
                pub.set_subscribed(True)
            if pub.subscribed and pub.track:
                kind = pub.kind
                if kind == rtc.TrackKind.KIND_VIDEO:
                    task = asyncio.create_task(handle_video_track(pub.track, room, session))
                    session.tasks.append(task)
                    log.info("video track subscribed from %s (existing)", p.identity)
                elif kind == rtc.TrackKind.KIND_AUDIO:
                    task = asyncio.create_task(handle_audio_track(pub.track, room, session))
                    session.tasks.append(task)
                    log.info("audio track subscribed from %s (existing)", p.identity)

    await session.start()

    # --- wait until the job ends (participant left / room closed) ---
    try:
        await asyncio.Event().wait()  # run forever; the framework cancels on shutdown
    except asyncio.CancelledError:
        pass
    finally:
        await session.stop()
        log.info("room session torn down for %s", room.name)


async def _init_stores() -> None:
    """Wire Postgres + Neo4j for this worker process (lifespan never runs here).

    Idempotent-safe: re-inits are cheap (pool + driver singleton). On DB outage the room
    still runs — extraction + face-name lookup degrade gracefully to log-and-skip.
    """
    from env import get_settings
    from graph import client as neo4j_client

    from postgres import session as pg_session

    settings = get_settings()
    try:
        pg_session.init_engine(settings.database_url)
    except Exception:  # noqa: BLE001 — DB down → room runs, extraction degrades
        log.exception("postgres init failed; memory persistence unavailable")
    try:
        await neo4j_client.init_driver(
            settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password
        )
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
