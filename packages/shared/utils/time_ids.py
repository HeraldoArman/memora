"""Pure-Python shared utils. Media helpers (frame→jpeg, audio→bytes) live in
apps/backend/perception (they need livekit/PIL); shared stays dep-light."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def now_utc() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(UTC)


def gen_id() -> str:
    """Random UUID4 as hex string (DB PKs, observation_ids, request_ids)."""
    return uuid.uuid4().hex


def iso_now() -> str:
    """ISO-8601 UTC timestamp string."""
    return now_utc().isoformat()


def aggregate_confidence(scores: list[float], *, weights: list[float] | None = None) -> float:
    """Weighted mean of confidence scores in [0,1].

    memory_pipeline.md §12 confidence model factors several sources; here we just combine
    per-source confidences. Equal weights when none given. Empty list → 0.0.
    """
    if not scores:
        return 0.0
    w = weights if weights is not None else [1.0] * len(scores)
    if len(w) != len(scores):
        raise ValueError(f"weights length {len(w)} != scores length {len(scores)}")
    total_w = sum(w)
    if total_w == 0:
        return 0.0
    return sum(s * wt for s, wt in zip(scores, w, strict=True)) / total_w
