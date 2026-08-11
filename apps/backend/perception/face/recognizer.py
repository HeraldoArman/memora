"""FaceRecognizer — InsightFace-backed detection + 512-d embedding.

Lazy-loaded: the model (~300MB buffalo_l) is initialized on first detect, not at import.
Behind an adapter so it can swap to a GPU microservice without touching perception wiring
(plan: GCP GPU fallback). CPU inference is heavy (~100-500ms/face) but acceptable at 1 FPS.

buffalo_l is non-commercial (research-only) — documented in README. Auto-downloads weights
to FACE_MODEL_ROOT on first init (needs network).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from env import get_settings

logger = logging.getLogger(__name__)

_FACE_APP = None  # lazy singleton


@dataclass
class DetectedFace:
    """One detected face from a frame."""

    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2 (int pixels)
    embedding: np.ndarray  # 512-d, L2-normalized
    det_score: float


def _load_app():
    """Initialize InsightFace FaceAnalysis once (lazy)."""
    global _FACE_APP
    if _FACE_APP is not None:
        return _FACE_APP
    from insightface.app import FaceAnalysis

    settings = get_settings()
    logger.info("loading insightface buffalo_l (CPU, lazy) from %s", settings.face_model_root)
    app = FaceAnalysis(
        name="buffalo_l",
        root=settings.face_model_root,
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=-1, det_size=(640, 640))
    _FACE_APP = app
    logger.info("insightface ready")
    return app


def preload() -> None:
    """Eagerly load the model at session start (avoids 9s stall on first frame)."""
    _load_app()


class FaceRecognizer:
    """Adapter over InsightFace. Detect faces → embeddings. Swap for an HTTP client impl
    when moving to a GPU worker (interface stays identical)."""

    def detect_and_embed(
        self, img: np.ndarray, *, max_num: int = 0, min_det_score: float = 0.5
    ) -> list[DetectedFace]:
        """Detect faces in img (BGR uint8 HxWx3). Returns [] if none. max_num=0 → all.

        min_det_score filters low-confidence detections (e.g. water bottles, shadows)
        so they don't produce spurious embeddings that surface as "Orang tidak dikenali".
        """
        app = _load_app()
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
