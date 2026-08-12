"""Track handler — wire subscribed video tracks to InsightFace.

AgentSession handles audio input/output to Gemini directly. This module only
runs the video loop for face recognition: sample frames → InsightFace →
tool_ctx.last_face. Gemini sees video separately via RoomOptions(video_input=True).
"""

from __future__ import annotations

import asyncio
import gc
import logging

log = logging.getLogger(__name__)


def _encode_jpeg(bgr) -> bytes | None:
    """Encode a BGR numpy array to JPEG bytes."""
    try:
        from perception.vision.sampler import _encode_jpeg as _enc

        return _enc(bgr)
    except Exception:  # noqa: BLE001
        log.debug("jpeg encode failed")
        return None


async def handle_video_track(
    track, room, tool_ctx, scene_understander=None, obs_engine=None
) -> asyncio.Task:
    """Spawn the video loop: sample frames → face identity + scene understanding.

    Returns the background task (caller stores it for cleanup).
    """
    from livekit import rtc

    from perception.face.recognizer import FaceRecognizer
    from perception.vision.sampler import FrameSampler

    log.info("handle_video_track: creating VideoStream + FrameSampler + FaceRecognizer")
    video_stream = rtc.VideoStream(track)
    sampler = FrameSampler(video_stream)
    recognizer = FaceRecognizer()

    async def _video_loop() -> None:
        log.info("video loop started — sampling frames for InsightFace + scene understanding")
        frame_count = 0
        try:
            async for frame in sampler.frames():
                frame_count += 1
                try:
                    bgr = frame["bgr"]
                    faces = await asyncio.to_thread(recognizer.detect_and_embed, bgr)
                    log.info(
                        "video frame %d: %dx%d faces=%d",
                        frame_count,
                        bgr.shape[1],
                        bgr.shape[0],
                        len(faces),
                    )
                    if faces:
                        log.debug(
                            "video frame %d: face detected (det_score=%.3f bbox=%s), running lookup",
                            frame_count,
                            getattr(faces[0], "det_score", 0),
                            getattr(faces[0], "bbox", None),
                        )
                        await _update_last_face(faces[0], tool_ctx, obs_engine)
                    else:
                        if tool_ctx.last_face is not None:
                            log.debug(
                                "video frame %d: no face detected, clearing stale last_face",
                                frame_count,
                            )
                            tool_ctx.last_face = None

                    # Step 3: scene understanding every 5 frames (~5s at 1 FPS)
                    if scene_understander is not None and frame_count % 5 == 0:
                        jpeg = _encode_jpeg(bgr)
                        if jpeg:
                            try:
                                scene = await scene_understander.understand(jpeg)
                                if scene:
                                    tool_ctx.last_scene = scene
                                    log.info(
                                        "scene understood: location=%s activity=%s confidence=%.2f",
                                        scene.get("location"),
                                        scene.get("activity"),
                                        scene.get("confidence", 0),
                                    )
                                    if obs_engine is not None:
                                        from dto.observations import SceneObservation

                                        await obs_engine.emit(
                                            SceneObservation(
                                                location=scene.get("location"),
                                                objects=scene.get("objects", []),
                                                activity=scene.get("activity"),
                                                confidence=scene.get("confidence", 0.8),
                                            )
                                        )
                            except Exception:  # noqa: BLE001
                                log.debug("scene understanding failed on frame %d", frame_count)

                    del bgr, faces
                    if frame_count % 5 == 0:
                        gc.collect()
                except Exception:  # noqa: BLE001
                    log.exception("face recognize failed on frame %d", frame_count)
        except asyncio.CancelledError:
            log.info("video loop cancelled (task cleanup)")
            raise
        except Exception:  # noqa: BLE001
            log.exception("video loop crashed unexpectedly")

    task = asyncio.create_task(_video_loop(), name="video-loop")
    log.info("video loop task spawned (name=video-loop)")
    return task


async def _update_last_face(detected, tool_ctx, obs_engine=None) -> None:
    """Look up face embedding → write result to tool_ctx.last_face + emit FaceObservation."""
    try:
        face_repo = tool_ctx.face_repo
        if face_repo is None:
            log.debug("face repo not available; skipping identity lookup")
            return
        log.debug(
            "face lookup: embedding shape=%s, repo size=%d",
            getattr(detected.embedding, "shape", None),
            face_repo.size,
        )
        result = face_repo.lookup(detected.embedding)
        name = None
        if result.person_id and (result.is_known or result.is_possible):
            try:
                from graph import repository as graph_repo

                log.debug(
                    "face lookup: resolving name for person_id=%s via graph", result.person_id
                )
                profile = await graph_repo.PersonRepo().get_person(result.person_id)
                if profile:
                    name = profile.get("name")
                    log.debug("face lookup: name resolved to %s", name)
                else:
                    log.debug("face lookup: person_id=%s has no profile in graph", result.person_id)
            except Exception:  # noqa: BLE001
                log.warning(
                    "face name lookup failed for %s; keeping name=None",
                    result.person_id,
                    exc_info=True,
                )

        if result.person_id is None:
            log.info(
                "face lookup: UNKNOWN score=%.3f (threshold known=%.2f possible=%.2f) — caching embedding",
                result.score,
                face_repo.known_threshold,
                face_repo.possible_threshold,
            )
        else:
            log.info(
                "face lookup: person_id=%s name=%s score=%.3f known=%s possible=%s",
                result.person_id,
                name,
                result.score,
                result.is_known,
                result.is_possible,
            )

        tool_ctx.last_face = {
            "embedding": detected.embedding,
            "person_id": result.person_id,
            "name": name,
            "score": float(result.score),
            "is_known": result.is_known,
            "is_possible": result.is_possible,
        }
        log.debug(
            "tool_ctx.last_face updated: person_id=%s name=%s known=%s possible=%s",
            result.person_id,
            name,
            result.is_known,
            result.is_possible,
        )
        if not result.is_known:
            tool_ctx.cache_unknown_embedding(detected.embedding)
            log.debug("cached unknown embedding (TTL=%ss)", tool_ctx.UNKNOWN_EMBEDDING_TTL_S)

        if obs_engine is not None:
            from dto.observations import FaceObservation

            await obs_engine.emit(
                FaceObservation(
                    person_id=result.person_id,
                    name=name,
                    confidence=float(result.score),
                    is_known=result.is_known,
                    is_possible_match=result.is_possible,
                    embedding=detected.embedding,
                )
            )
    except Exception:  # noqa: BLE001
        log.exception("face lookup failed")


# --- self-check: _update_last_face with None repo is a no-op ---
def _self_check() -> None:  # pragma: no cover
    import asyncio
    from types import SimpleNamespace

    from tools import ToolContext

    ctx = ToolContext()
    detected = SimpleNamespace(embedding=None)
    asyncio.run(_update_last_face(detected, ctx))
    assert ctx.last_face is None  # no repo → no update
    print("track_handler self-check OK: no repo → no-op")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
