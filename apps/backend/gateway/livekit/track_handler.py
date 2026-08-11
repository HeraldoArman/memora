"""Track handler — wire subscribed video/audio tracks to perception + reasoning.

On track_subscribed, spawn two background tasks per track:
  - Video track → FrameSampler (1 FPS) → for each frame:
      * FaceRecognizer.detect_and_embed → FaceRepository.lookup → FaceObservation emit
        into the ObservationEngine (identity path, deterministic).
      * agent.feed_video(jpeg) → Gemini Live (scene-understanding path).
      * sync the new ToolContext.current_context from WorkingMemory after each emit so
        tools see fresh observation data.
  - Audio track → SpeechForwarder → agent.feed_audio (Gemini Live realtime audio in).

Ponytail: one task per track, no per-frame threading. Face recognition runs inline on
the sampled frame at 1 FPS (CPU-bound but bounded). The forwarder is reused as-is; we
give it a shim exposing send_realtime_input so we don't modify the tested forwarder.

The video loop also bridges the FaceObservation into the ObservationEngine — the
recognizer's embedding is attached so search_person_by_face can use it.
"""

from __future__ import annotations

import asyncio
import logging

from dto.observations import FaceObservation, SceneObservation

log = logging.getLogger(__name__)


class _AudioShim:
    """Adapts the agent's feed_audio to the SpeechForwarder's send_realtime_input(audio=blob) API.

    SpeechForwarder calls live_session.send_realtime_input(audio=Blob). We unwrap the Blob
    (mime_type audio/pcm;rate=N, data=bytes) and call agent.feed_audio(data, sample_rate=N).
    Ponytail: shim rather than modifying the tested forwarder.
    """

    def __init__(self, agent) -> None:
        self._agent = agent

    async def send_realtime_input(self, *, audio=None, **_kw) -> None:
        if audio is None:
            return
        data = getattr(audio, "data", None)
        if not data:
            return
        # mime_type is "audio/pcm;rate=16000" → parse rate
        rate = 16000
        mime = getattr(audio, "mime_type", "") or ""
        if "rate=" in mime:
            try:
                rate = int(mime.split("rate=")[1].split(";")[0])
            except (ValueError, IndexError):
                pass
        await self._agent.feed_audio(bytes(data), sample_rate=rate)


async def handle_video_track(track, room, session) -> asyncio.Task:
    """Spawn the video loop: sample frames → face identity + Gemini video.

    Returns the background task (caller stores it for cleanup).
    """
    from livekit import rtc

    from perception.face.recognizer import FaceRecognizer
    from perception.vision.sampler import FrameSampler

    video_stream = rtc.VideoStream(track)
    sampler = FrameSampler(video_stream)
    recognizer = FaceRecognizer()
    # ponytail: scene understanding every 2s for near-realtime. Response objects
    # are explicitly cleared in understander.py after parse to prevent leak.
    _scene_counter = 0
    _SCENE_INTERVAL = 2

    async def _video_loop() -> None:
        nonlocal _scene_counter
        log.info("video loop started")
        try:
            async for frame in sampler.frames():
                # 1. face identity path (deterministic; Gemini can't match a gallery)
                try:
                    faces = recognizer.detect_and_embed(frame["bgr"])
                    log.info(
                        "frame: %dx%d faces=%d",
                        frame["bgr"].shape[1],
                        frame["bgr"].shape[0],
                        len(faces),
                    )
                    if faces:
                        f = faces[0]
                        obs = await _lookup_face(f.embedding, session.face_repo)
                        if obs is not None:
                            if not obs.is_known:
                                session.tool_ctx.cache_unknown_embedding(obs.embedding)
                            await session.observation_engine.emit(obs)
                except Exception:  # noqa: BLE001 — perception errors must not kill the loop
                    log.exception("face recognize failed")

                # 1.5 scene understanding path (Gemini Vision, every 5s not 1 FPS)
                _scene_counter += 1
                if _scene_counter >= _SCENE_INTERVAL:
                    _scene_counter = 0
                    try:
                        su = getattr(session, "scene_understander", None)
                        if su is not None:
                            scene_data = await su.understand(frame["jpeg"])
                            if scene_data and scene_data.get("location"):
                                await session.observation_engine.emit(
                                    SceneObservation(
                                        location=scene_data["location"],
                                        objects=scene_data.get("objects", []),
                                        activity=scene_data.get("activity"),
                                        confidence=scene_data.get("confidence", 0.8),
                                    )
                                )
                    except Exception:  # noqa: BLE001
                        log.exception("scene understand failed")

                # ponytail: no feed_video to Gemini Live — the native-audio model gets
                # visual context through tool calls (visible_people, current_scene).
                # Sending raw JPEGs to send_realtime_input(video=...) caused ~66MB/s
                # memory growth in the SDK (274MB→3.2GB in 3min, process killed).

                # 2. sync tool context so tools see fresh CurrentContext
                session.sync_context()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("video loop crashed")

    task = asyncio.create_task(_video_loop(), name="video-loop")
    return task


async def _lookup_face(embedding, face_repo) -> FaceObservation | None:
    """Identify an embedding via the session's face repo; return a FaceObservation.

    `face_repo` is the RoomSession's FaceRepository (built at session create — the worker
    process doesn't run the FastAPI lifespan). None repo → no identity path (keeps the
    video loop alive if face infra isn't wired). FaceRepository is sync (faiss-cpu search
    is in-process); we keep the function async so callers can `await` uniformly.
    """
    try:
        if face_repo is None:
            log.debug("face repo not available; skipping identity lookup")
            return None
        result = face_repo.lookup(embedding)  # sync: faiss search is in-process
        # Resolve person_id → name via the graph so fuse() can surface the person in
        # CurrentContext.visible_people (it only adds known+named observations). Graph
        # outage must NOT drop the observation — degrade to name=None and still emit.
        name = None
        if result.person_id and (result.is_known or result.is_possible):
            try:
                from graph import repository as graph_repo

                profile = await graph_repo.PersonRepo().get_person(result.person_id)
                if profile:
                    name = profile.get("name")
            except Exception:  # noqa: BLE001
                log.warning("face name lookup failed for %s; keeping name=None", result.person_id)
        if result.person_id is None:
            log.info(
                "face lookup: unknown score=%.3f (threshold known=%.2f possible=%.2f)",
                result.score,
                face_repo.known_threshold,
                face_repo.possible_threshold,
            )
        else:
            log.info(
                "face lookup: %s name=%s score=%.3f known=%s possible=%s",
                result.person_id,
                name,
                result.score,
                result.is_known,
                result.is_possible,
            )
        return FaceObservation(
            person_id=result.person_id,
            name=name,
            confidence=float(result.score),
            is_known=result.is_known,
            is_possible_match=result.is_possible,
            embedding=embedding,
        )
    except Exception:  # noqa: BLE001
        log.exception("face lookup failed")
        return None


async def handle_audio_track(track, room, session) -> asyncio.Task:
    """Spawn the audio forwarder loop: AudioStream → Gemini Live.

    Returns the background task (caller stores it for cleanup).
    """
    from livekit import rtc

    from perception.speech.forwarder import SpeechForwarder

    audio_stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
    shim = _AudioShim(session.agent)
    forwarder = SpeechForwarder(audio_stream, shim)

    async def _audio_loop() -> None:
        try:
            await forwarder.run()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — gemini ws closed; receive loop reconnects
            log.info("audio forwarder ended (gemini reconnecting); loop exits cleanly")

    task = asyncio.create_task(_audio_loop(), name="audio-loop")
    return task


# --- self-check: audio shim rate parse + dispatch ---
def _self_check() -> None:  # pragma: no cover
    import asyncio

    from google.genai import types

    class _Agent:
        def __init__(self):
            self.calls = []

        async def feed_audio(self, data, *, sample_rate):
            self.calls.append((data, sample_rate))

    agent = _Agent()
    shim = _AudioShim(agent)
    blob = types.Blob(mime_type="audio/pcm;rate=16000", data=b"\x00\x01\x02")
    asyncio.run(shim.send_realtime_input(audio=blob))
    assert agent.calls == [(b"\x00\x01\x02", 16000)], agent.calls

    # weird rate parsed, no audio = no-op
    blob2 = types.Blob(mime_type="audio/pcm;rate=8000", data=b"\x04")
    asyncio.run(shim.send_realtime_input(audio=blob2))
    assert agent.calls[-1] == (b"\x04", 8000)
    asyncio.run(shim.send_realtime_input(audio=None))
    assert len(agent.calls) == 2
    print("track_handler self-check OK: shim parses rate + dispatches feed_audio")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
