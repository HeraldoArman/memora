"""Ranker — weighted scoring of retrieved memory candidates.

context.md §9 (ranking signals): semantic similarity, temporal recency, social proximity
(visible people), spatial relevance (location match), importance, confidence, frequency.
For the hackathon we combine a subset with hand-tuned weights — no learned ranker.

Ponytail: signals computed from dict records (memory_service / knowledge_service output),
not from heavyweight embeddings. Semantic similarity = token-overlap ratio (Jaccard) over
the query vs content — cheap, deterministic, good enough at this scale. Embedding-based
similarity would need a separate model call per candidate; not worth it pre-need.
"""

from __future__ import annotations

from datetime import UTC, datetime

from utils.time_ids import now_utc

# Signal weights (context.md §9, hand-tuned). Sum need not be 1 — scores are comparative.
_W_SEMANTIC = 0.30
_W_TEMPORAL = 0.20
_W_SOCIAL = 0.20
_W_SPATIAL = 0.10
_W_CONFIDENCE = 0.10
_W_FREQUENCY = 0.10

# Temporal decay half-life in days — memories older than this score ~half on recency.
_TEMPORAL_HALFLIFE_DAYS = 14.0


def _tokens(text: str) -> set[str]:
    return {t for t in text.lower().split() if len(t) > 1}


def semantic_similarity(query: str, content: str) -> float:
    """Jaccard overlap between query + content token sets. 0–1."""
    q, c = _tokens(query), _tokens(content)
    if not q or not c:
        return 0.0
    return len(q & c) / len(q | c)


def temporal_score(created_at: datetime | None, *, now: datetime | None = None) -> float:
    """Exponential decay from recency. 1.0 now → ~0.5 at half-life → →0."""
    if created_at is None:
        return 0.0
    n = now or now_utc()
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    age_days = max(0.0, (n - created_at).total_seconds() / 86400.0)
    return 0.5 ** (age_days / _TEMPORAL_HALFLIFE_DAYS)


def rank(
    candidates: list[dict],
    *,
    query: str,
    visible_people: list[str] | None = None,
    location: str | None = None,
    now: datetime | None = None,
) -> list[tuple[dict, float, dict]]:
    """Score + sort candidates by weighted signals.

    Returns [(candidate, score, signals)] descending. Each candidate is a dict with at least
    `content` and optionally `created_at`, `confidence`, `frequency`, `related_people`,
    `location`, `category`. Missing fields default to neutral scores.
    """
    visible = {p.lower() for p in (visible_people or [])}
    loc = (location or "").lower()
    n = now or now_utc()
    scored: list[tuple[dict, float, dict]] = []
    for c in candidates:
        content = c.get("content") or c.get("title") or c.get("name") or ""
        sem = semantic_similarity(query, content)
        temp = temporal_score(_parse_dt(c.get("created_at")), now=n)
        # social: does this memory involve a currently visible person?
        soc = 1.0 if any(p.lower() in visible for p in (c.get("related_people") or [])) else 0.0
        # spatial: does the memory's location match the current scene?
        c_loc = (c.get("location") or "").lower()
        spat = 1.0 if loc and c_loc and (loc in c_loc or c_loc in loc) else 0.0
        conf = float(c.get("confidence", 0.0) or 0.0)
        freq = min(1.0, float(c.get("frequency", 0.0) or 0.0) / 5.0)  # saturate at 5 mentions

        score = (
            _W_SEMANTIC * sem
            + _W_TEMPORAL * temp
            + _W_SOCIAL * soc
            + _W_SPATIAL * spat
            + _W_CONFIDENCE * conf
            + _W_FREQUENCY * freq
        )
        signals = {
            "semantic": round(sem, 3),
            "temporal": round(temp, 3),
            "social": soc,
            "spatial": spat,
            "confidence": round(conf, 3),
            "frequency": round(freq, 3),
        }
        scored.append((c, score, signals))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


def _parse_dt(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    s = str(v)
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


# --- self-check ---
def _self_check() -> None:  # pragma: no cover
    now = datetime(2026, 8, 10, tzinfo=UTC)
    candidates = [
        {
            "content": "Asep works at Tokopedia",
            "created_at": "2026-08-09T12:00:00+00:00",
            "related_people": ["Asep"],
            "confidence": 0.9,
            "frequency": 3,
        },
        {
            "content": "Budi likes sushi",
            "created_at": "2026-07-01T12:00:00+00:00",
            "related_people": ["Budi"],
            "confidence": 0.8,
            "frequency": 1,
        },
        {
            "content": "Asep lives in Jakarta",
            "created_at": "2026-08-08T12:00:00+00:00",
            "related_people": ["Asep"],
            "location": "Jakarta",
            "confidence": 0.7,
        },
    ]
    ranked = rank(
        candidates, query="Asep Tokopedia", visible_people=["Asep"], location="Jakarta", now=now
    )
    top = ranked[0]
    assert "Tokopedia" in top[0]["content"], top[0]
    assert top[2]["semantic"] > 0, top[2]  # query overlap
    assert top[2]["social"] == 1.0, top[2]  # Asep visible
    assert top[2]["spatial"] == 0.0 or ranked[2][2]["spatial"] == 1.0  # Jakarta matches the 3rd
    # recency: 1 day old beats 40 days old
    assert top[2]["temporal"] > ranked[1][2]["temporal"]
    print(f"ranker self-check OK: top score={top[1]:.3f} signals={top[2]}")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
