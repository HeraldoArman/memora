"""Filter — gate extraction on content worth extracting.

memory_pipeline.md §4 (filtering): not every CurrentContext snapshot should trigger an
extraction call (cost + noise). Rule-first: skip empty/trivial speech, skip pure device
telemetry, keep speech with substantive content and scene changes with a new location.

Ponytail: a length + keyword heuristic is enough for the hackathon. A learned salience
model would be over-engineering here.
"""

from __future__ import annotations

# Too short / non-substantive to extract.
_TRIVIAL = {"apa ini", "apa itu", "ya", "tidak", "oh", "hmm", "eh", "hai", "halo"}


def should_extract(content: str | None) -> bool:
    """True if `content` (speech or transcript text) is worth a Gemini extraction call."""
    if not content:
        return False
    text = content.strip().lower()
    if len(text) < 6:  # too short to carry an entity/relation
        return False
    if text in _TRIVIAL:
        return False
    return True


# --- self-check ---
def _self_check() -> None:  # pragma: no cover
    assert should_extract(None) is False
    assert should_extract("") is False
    assert should_extract("apa ini") is False
    assert should_extract("ya") is False
    assert should_extract("I'm Asep, I work at Tokopedia, I like sushi") is True
    print("filter self-check OK")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
