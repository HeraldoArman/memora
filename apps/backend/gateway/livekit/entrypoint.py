"""LiveKit agent entrypoint — the job dispatched by the worker.

WorkerOptions(entrypoint_fnc=entrypoint) → the framework calls entrypoint(ctx: JobContext)
when a room is assigned. We:
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
from livekit.agents import JobContext, WorkerOptions

from gateway.livekit.data_channel import handle_data_received
from gateway.livekit.track_handler import handle_audio_track, handle_video_track
from gateway.session import RoomSession

log = logging.getLogger(__name__)


async def entrypoint(ctx: JobContext) -> None:
    """Per-room job: connect, build session, wire track + data handlers, run until closed."""
    await ctx.connect(auto_subscribe=True)
    room = ctx.room
    log.info("job connected to room %s", room.name)

    # The worker is a separate process — it never runs the FastAPI lifespan, so Postgres +
    # Neo4j are wired here before any session/turn touches them (extraction, face names).
    await _init_stores()
    session = await RoomSession.create(room)
    await session.start()

    # --- wire track + data handlers ---
    @room.on("track_subscribed")
    def _on_track(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        kind = publication.kind
        if kind == rtc.TrackKind.KIND_VIDEO:
            task = asyncio.create_task(handle_video_track(track, room, session))
            session.tasks.append(task)
            log.info("video track subscribed from %s", participant.identity)
        elif kind == rtc.TrackKind.KIND_AUDIO:
            task = asyncio.create_task(handle_audio_track(track, room, session))
            session.tasks.append(task)
            log.info("audio track subscribed from %s", participant.identity)

    @room.on("data_received")
    def _on_data(payload: bytes | str, participant: rtc.RemoteParticipant, topic: str):
        asyncio.create_task(handle_data_received(payload, topic, session.observation_engine))

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


def build_worker_options() -> WorkerOptions:
    """WorkerOptions for the livekit-agent worker process."""
    return WorkerOptions(entrypoint_fnc=entrypoint)


# --- self-check: entrypoint + WorkerOptions construction (no live connection) ---
def _self_check() -> None:  # pragma: no cover
    opts = build_worker_options()
    assert opts is not None
    # entrypoint_fnc is the canonical attr on WorkerOptions across versions
    fn = getattr(opts, "entrypoint_fnc", None) or getattr(opts, "entrypoint", None)
    assert fn is entrypoint, "entrypoint not wired into WorkerOptions"
    print("entrypoint self-check OK: WorkerOptions(entrypoint_fnc=entrypoint)")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
