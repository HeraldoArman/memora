"""FaceRecognizer — InsightFace-backed detection + 512-d embedding.

Lazy-loaded: the model (~300MB buffalo_l) is initialized on first detect, not at import.
Behind an adapter so it can swap to a GPU microservice without touching perception wiring
(plan: GCP GPU fallback). CPU inference is heavy (~100-500ms/face) but acceptable at 0.5 FPS.

bison_l is non-commercial (research-only) — documented in README. Auto-downloads weights
to FACE_MODEL_ROOT on first init (needs network).

Known issue: ONNX Runtime CPUExecutionProvider leaks ~20-50MB per session.run() call.
This is a confirmed upstream bug (onnxruntime#9313, #22271; insightface#1659) open since
2021. We work around it by recreating the session every _MAX_INFERENCE_CALLS calls.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np
from env import get_settings

logger = logging.getLogger(__name__)

_FACE_APP = None  # lazy singleton
_FACE_LOCK = threading.Lock()
_INFERENCE_COUNT = 0
# Recreate the ONNX session every N calls to flush leaked memory.
# At 0.5 FPS, 30 calls = ~60s. Each leak is ~20-50MB, so 30 calls = ~600MB-1.5GB
# before reset. The recreate takes ~4s (model reload) but frees all leaked memory.
_MAX_INFERENCE_CALLS = 30


@dataclass
class DetectedFace:
    """One detected face from a frame."""

    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2 (int pixels)
    embedding: np.ndarray  # 512-d, L2-normalized
    det_score: float


def _load_app():
    """Initialize InsightFace FaceAnalysis once (lazy). Thread-safe via lock."""
    global _FACE_APP
    if _FACE_APP is not None:
        return _FACE_APP
    with _FACE_LOCK:
        if _FACE_APP is not None:
            return _FACE_APP
        _FACE_APP = _create_app()
        return _FACE_APP


def _create_app():
    """Create a fresh FaceAnalysis instance (used for initial load + recycle)."""
    from insightface.app import FaceAnalysis

    settings = get_settings()
    logger.info("loading insightface buffalo_l (CPU, lazy) from %s", settings.face_model_root)
    app = FaceAnalysis(
        name="buffalo_l",
        root=settings.face_model_root,
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=-1, det_size=(640, 640))
    logger.info("insightface ready")
    return app


def _recycle_app():
    """Delete + recreate the ONNX session to flush leaked memory.

    ONNX Runtime CPUExecutionProvider leaks ~20-50MB per run() call (upstream bug
    #9313, open since 2021). Recreating the session frees all accumulated memory.
    Takes ~4s (model reload) but prevents OOM kills.
    """
    global _FACE_APP, _INFERENCE_COUNT
    with _FACE_LOCK:
        old = _FACE_APP
        _FACE_APP = None
        _INFERENCE_COUNT = 0
        if old is not None:
            del old
        import gc

        gc.collect()
        logger.info("recycling insightface session (ONNX CPU memory leak workaround)")
        _FACE_APP = _create_app()


def preload() -> None:
    """Eagerly load the model at session start (avoids 9s stall on first frame)."""
    _load_app()


class FaceRecognizer:
    """Adapter over InsightFace. Detect faces → embeddings. Swap for an HTTP client impl
    when moving to a GPU worker (interface stays identical)."""

    def detect_and_embed(
        self, img: np.ndarray, *, max_num: int = 0, min_det_score: float = 0.3
    ) -> list[DetectedFace]:
        """Detect faces in img (BGR uint8 HxWx3). Returns [] if none. max_num=0 → all.

        min_det_score filters low-confidence detections (e.g. water bottles, shadows)
        so they don't produce spurious embeddings that surface as "Orang tidak dikenali".
        """
        global _INFERENCE_COUNT
        app = _load_app()
        _INFERENCE_COUNT += 1
        if _INFERENCE_COUNT >= _MAX_INFERENCE_CALLS:
            _recycle_app()
            app = _FACE_APP
        faces = app.get(img, max_num=max_num)
        result: list[DetectedFace] = []
        for f in faces:
            if f.det_score < min_det_score:
                continue
            emb = f.normed_embedding
            if emb is None:
                continue
            bbox = tuple(int(round(x)) for x in f.bbox[:4])
            result.append(
                DetectedFace(
                    bbox=bbox,
                    embedding=np.asarray(emb, dtype=np.float32),
                    det_score=float(f.det_score),
                )
            )
        return result


# --- self-check: load model + run on a synthetic image ---
async def _self_check() -> None:  # pragma: no cover
    # Synthetic noise image — detection likely finds 0 faces; verifies the pipeline loads.
    img = (np.random.default_rng(0).random((640, 640, 3)) * 255).astype(np.uint8)
    rec = FaceRecognizer()
    faces = rec.detect_and_embed(img)
    assert all(f.embedding.shape == (512,) for f in faces), "embedding dim != 512"
    print(f"recognizer self-check: {len(faces)} faces, model loaded OK")


if __name__ == "__main__":  # pragma: no cover
    import asyncio

    asyncio.run(_self_check())
