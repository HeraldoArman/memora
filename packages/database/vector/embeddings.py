"""Face embedding helpers.

InsightFace returns normed embeddings (L2=1) so inner product = cosine similarity.
These helpers guarantee normalization regardless of upstream source.
"""

from __future__ import annotations

import numpy as np


def l2_normalize(vector: np.ndarray) -> np.ndarray:
    """L2-normalize a single vector or a batch. Inner product over normalized vectors == cosine."""
    vec = np.asarray(vector, dtype=np.float32)
    if vec.ndim == 1:
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec
    # batch (n, d)
    norms = np.linalg.norm(vec, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vec / norms).astype(np.float32)
