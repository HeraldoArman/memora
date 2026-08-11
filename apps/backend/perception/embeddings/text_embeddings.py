"""Text embedder — query/memory embeddings via Gemini text-embedding-004.

Used by the retriever for semantic memory search (replacing name-substring + Jaccard
token overlap). Also used by the consolidator to embed facts as they're stored.

Ponytail: one model call per embed, L2-normalized for cosine similarity via FAISS
IndexFlatIP. Failure → None (retriever falls back to name-substring).
"""

from __future__ import annotations

import logging

import numpy as np
from env import get_settings

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "text-embedding-004"
_DEFAULT_DIM = 768


class TextEmbedder:
    """Embed text into L2-normalized vectors via Gemini."""

    def __init__(
        self, client=None, *, model: str = _DEFAULT_MODEL, dim: int = _DEFAULT_DIM
    ) -> None:
        self._client = client
        self.model = model
        self.dim = dim

    def _get_client(self):
        if self._client is not None:
            return self._client
        from google import genai

        self._client = genai.Client(api_key=get_settings().gemini_api_key)
        return self._client

    async def embed(self, text: str) -> np.ndarray | None:
        """Embed a single text → L2-normalized 768-d vector. None on failure/empty."""
        if not text or not text.strip():
            return None
        try:
            client = self._get_client()
            resp = await client.aio.models.embed_content(
                model=self.model,
                contents=text,
            )
            vecs = _extract_embeddings(resp)
            if not vecs:
                return None
            return _l2_normalize(vecs[0])
        except Exception as e:  # noqa: BLE001
            log.warning("text embed failed: %s", e)
            return None

    async def embed_batch(self, texts: list[str]) -> list[np.ndarray | None]:
        """Embed multiple texts. Returns parallel list; None entries for failures."""
        if not texts:
            return []
        try:
            client = self._get_client()
            resp = await client.aio.models.embed_content(
                model=self.model,
                contents=texts,
            )
            vecs = _extract_embeddings(resp)
            if not vecs:
                return [None] * len(texts)
            return [_l2_normalize(v) if v is not None else None for v in vecs]
        except Exception as e:  # noqa: BLE001
            log.warning("batch embed failed: %s", e)
            return [None] * len(texts)


def _extract_embeddings(resp) -> list[np.ndarray | None]:
    """Pull embeddings from an EmbedContentResponse."""
    embeddings = getattr(resp, "embeddings", None)
    if embeddings is None:
        return []
    out = []
    for e in embeddings:
        values = getattr(e, "values", None)
        if values:
            out.append(np.array(values, dtype=np.float32))
        else:
            out.append(None)
    return out


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    """L2-normalize so inner product = cosine similarity."""
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


# --- self-check (no API): normalize + extract shape ---
def _self_check() -> None:  # pragma: no cover
    import asyncio

    v = np.array([3.0, 4.0], dtype=np.float32)
    n = _l2_normalize(v)
    assert abs(np.linalg.norm(n) - 1.0) < 1e-6, n

    # empty text → None (no API call)
    assert asyncio.run(TextEmbedder(client=object()).embed("")) is None
    assert asyncio.run(TextEmbedder(client=object()).embed("   ")) is None

    # batch empty → []
    assert asyncio.run(TextEmbedder(client=object()).embed_batch([])) == []

    print("text embedder self-check OK: normalize + empty guards")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
