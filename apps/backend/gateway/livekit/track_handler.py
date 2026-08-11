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
import gc
import logging

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
    """Spawn the video loop: sample frames → face identity.

    refactor/bare-minimum: writes face result directly to tool_ctx.last_face instead
    of going through ObservationEngine → WorkingMemory → sync_context.

    Returns the background task (caller stores it for cleanup).
    """
    from livekit import rtc

    from perception.face.recognizer import FaceRecognizer
    from perception.vision.sampler import FrameSampler

    video_stream = rtc.VideoStream(track)
    sampler = FrameSampler(video_stream)
    recognizer = FaceRecognizer()

    async def _video_loop() -> None:
        log.info("video loop started")
        frame_count = 0
        try:
            async for frame in sampler.frames():
                frame_count += 1
                try:
                    bgr = frame["bgr"]
                    # run face detection in a thread so it doesn't block the
                    # event loop (ONNX CPU inference takes 1-2s; blocking
                    # prevents Gemini connect task + receive loop from running)
                    faces = await asyncio.to_thread(recognizer.detect_and_embed, bgr)
                    log.info(
                        "frame: %dx%d faces=%d",
                        bgr.shape[1],
                        bgr.shape[0],
                        len(faces),
                    )
                    if faces:
                        f = faces[0]
                        await _update_last_face(f, session)
                    del bgr, faces
                    if frame_count % 5 == 0:
                        gc.collect()
                except Exception:  # noqa: BLE001 — perception errors must not kill the loop
                    log.exception("face recognize failed")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("video loop crashed")

    task = asyncio.create_task(_video_loop(), name="video-loop")
    return task


async def _update_last_face(detected, session) -> None:
    """Look up face embedding → write result directly to tool_ctx.last_face."""
    try:
        face_repo = session.face_repo
        if face_repo is None:
            log.debug("face repo not available; skipping identity lookup")
            return
        result = face_repo.lookup(detected.embedding)
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

        # Write directly to tool_ctx — no observation engine, no working memory
        session.tool_ctx.last_face = {
            "embedding": detected.embedding,
            "person_id": result.person_id,
            "name": name,
            "score": float(result.score),
            "is_known": result.is_known,
            "is_possible": result.is_possible,
        }
        if not result.is_known:
            session.tool_ctx.cache_unknown_embedding(detected.embedding)
    except Exception:  # noqa: BLE001
        log.exception("face lookup failed")


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
