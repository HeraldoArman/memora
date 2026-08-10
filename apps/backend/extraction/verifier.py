"""Verifier — confidence scoring for extracted knowledge.

memory_pipeline.md §12 (verification): each extracted item gets a ConfidenceLevel
(Accept / Reject / Require confirmation / Lower confidence). Rule-first:

- LLM confidence ≥ 0.85 → ACCEPT.
- ≥ 0.5 → LOWER_CONFIDENCE (keep but down-weight).
- < 0.5 → REJECT (drop).
- Explicit first-person statements ("I'm Asep", "I work at...") get a small boost —
  the speaker is asserting about themselves, a strong provenance signal.

Ponytail: no source-corroboration cross-check (would need multiple independent sources).
For a hackathon single-device feed, LLM confidence + provenance heuristic is enough.
"""

from __future__ import annotations

from constants import ConfidenceLevel

_FIRST_PERSON = ("i ", "i'", "i'm", "im", "aku", "saya", "gue", "gw")


def _is_first_person(text: str) -> bool:
    lowered = text.lower().strip()
    return any(lowered.startswith(p) for p in _FIRST_PERSON)


def first_person_boost(confidence: float, text: str) -> float:
    """Return the confidence for a single fact, boosted if it is a first-person statement.

    verify() applies the boost to a whole turn's extraction; this is the per-fact form so
    individual facts that are first-person assertions get the provenance bump independently.
    """
    if text and _is_first_person(text):
        return min(1.0, confidence + 0.1)
    return confidence


def verify(confidence: float, *, content: str = "") -> ConfidenceLevel:
    """Return a ConfidenceLevel for one extraction."""
    score = confidence
    if content and _is_first_person(content):
        score = min(1.0, score + 0.1)  # first-person provenance boost
    if score >= 0.85:
        return ConfidenceLevel.ACCEPT
    if score >= 0.5:
        return ConfidenceLevel.LOWER_CONFIDENCE
    return ConfidenceLevel.REJECT


def accepted(level: ConfidenceLevel) -> bool:
    """Whether a fact at this level should be written to the stores."""
    return level in (ConfidenceLevel.ACCEPT, ConfidenceLevel.LOWER_CONFIDENCE)


# --- self-check ---
def _self_check() -> None:  # pragma: no cover
    assert verify(0.9) is ConfidenceLevel.ACCEPT
    assert verify(0.6) is ConfidenceLevel.LOWER_CONFIDENCE
    assert verify(0.3) is ConfidenceLevel.REJECT
    # first-person boost: 0.8 → 0.9 → ACCEPT
    assert verify(0.8, content="I'm Asep") is ConfidenceLevel.ACCEPT
    assert verify(0.8, content="apa ini?") is ConfidenceLevel.LOWER_CONFIDENCE
    assert accepted(ConfidenceLevel.ACCEPT) is True
    assert accepted(ConfidenceLevel.REJECT) is False
    print("verifier self-check OK")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
