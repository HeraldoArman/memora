"""Track handler — store video frames + run scene understanding.

Face recognition (InsightFace) is NOT run here — it runs on-demand when a tool
calls ctx.refresh_face(). This keeps the asyncio event loop (audio pump) free
from ONNX inference + recycling stalls. The video loop just stores the latest
BGR frame in tool_ctx.last_frame and fires scene understanding every 5 frames.
"""

from __future__ import annotations

import asyncio
import logging
import time

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

    from perception.vision.sampler import FrameSampler

    log.info("handle_video_track: creating VideoStream + FrameSampler")
    video_stream = rtc.VideoStream(track)
    sampler = FrameSampler(video_stream)

    scene_task: asyncio.Task | None = None  # ponytail: single-flight guard for scene understanding

    async def _video_loop() -> None:
        nonlocal scene_task
        log.info("video loop started — storing frames + scene understanding")
        frame_count = 0
        t_prev = None
        try:
            async for frame in sampler.frames():
                frame_count += 1
                t0 = time.perf_counter()
                try:
                    bgr = frame["bgr"]
                    # Store latest frame for on-demand face recognition (tools call
                    # ctx.refresh_face() when they need identity — no more 30x/min ONNX)
                    tool_ctx.last_frame = bgr
                    log.info(
                        "video frame %d: %dx%d stored in %.1fms (face recognition deferred "
                        "to tool call)",
                        frame_count,
                        bgr.shape[1],
                        bgr.shape[0],
                        (time.perf_counter() - t0) * 1000,
                    )

                    # Step 3: scene understanding every 5 frames (~5s at 1 FPS)
                    # ponytail: single-flight guard — skip if previous call still in flight.
                    # Prevents task pile-up on a hung Gemini call AND out-of-order last_scene
                    # writes (old slow response overwriting a newer location).
                    if (
                        scene_understander is not None
                        and frame_count % 5 == 0
                        and (scene_task is None or scene_task.done())
                    ):
                        jpeg = _encode_jpeg(bgr)
                        if jpeg:
                            jpeg_ms = (time.perf_counter() - t0) * 1000
                            log.info(
                                "scene understanding triggered: frame=%d jpeg=%d bytes "
                                "encode_ms=%.1f",
                                frame_count,
                                len(jpeg),
                                jpeg_ms,
                            )
                            scene_task = asyncio.create_task(
                                _understand_scene(jpeg, tool_ctx, scene_understander, obs_engine)
                            )
                            scene_task.add_done_callback(
                                lambda t: log.info("scene task done: cancelled=%s", t.cancelled())
                            )

                    del bgr
                    # per-frame cadence: gap between consumer deliveries. If this
                    # climbs, the pipe (SFU → sampler) is throttling or dropping.
                    gap_ms = (time.perf_counter() - t_prev) * 1000 if t_prev is not None else 0.0
                    t_prev = time.perf_counter()
                    log.info(
                        "frame %d processed: total_ms=%.1f gap_from_prev_ms=%.1f",
                        frame_count,
                        (t_prev - t0) * 1000,
                        gap_ms,
                    )
                except Exception:  # noqa: BLE001
                    log.exception("video frame %d failed", frame_count)
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
        # Offload sync FAISS search (l2_normalize + index.search) off the event loop —
        # matches detect_and_embed at line 56. Running it inline blocked the Gemini
        # Live audio pump every frame.
        result = await asyncio.to_thread(face_repo.lookup, detected.embedding)
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


async def _understand_scene(jpeg: bytes, tool_ctx, scene_understander, obs_engine=None) -> None:
    """Run scene understanding off the video loop so face recognition never blocks."""
    t0 = time.perf_counter()
    try:
        scene = await scene_understander.understand(jpeg)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if scene:
            tool_ctx.last_scene = scene
            log.info(
                "scene understood: location=%s activity=%s confidence=%.2f took_ms=%.1f",
                scene.get("location"),
                scene.get("activity"),
                scene.get("confidence", 0),
                elapsed_ms,
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
        else:
            log.warning("scene understanding returned nothing took_ms=%.1f", elapsed_ms)
    except Exception:  # noqa: BLE001
        log.warning("scene understanding failed took_ms=%.1f", (time.perf_counter() - t0) * 1000)


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
