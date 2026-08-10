"""Classifier — map extracted entities to MemoryCategory.

knowledge_extraction.md §7 (classification). The LLM already assigns a `category` string
per entity (in the EXTRACTION_SCHEMA enum). This stage validates/normalizes it to the
MemoryCategory enum and maps the extraction-only Food category → Preference when consolidating
into the graph (Food has no dedicated label; preferences are the durable form).

Rule-first: trust the LLM's category when it's a valid enum value; default to Person for
names and Object for anything unrecognized. This keeps the pipeline robust to schema drift.
"""

from __future__ import annotations

from constants import MemoryCategory

_VALID = {c.value for c in MemoryCategory}

# Food → Preference when written to the graph (no Food label; preferences are durable).
_GRAPH_MAP = {
    MemoryCategory.FOOD: MemoryCategory.PREFERENCE,
}


def classify(category: str | None, *, name: str = "") -> MemoryCategory:
    """Return the validated MemoryCategory for an entity.

    Trust the LLM category if valid; else infer from the name (capitalized → Person).
    """
    if category and category in _VALID:
        return MemoryCategory(category)
    if name and name[0].isupper():
        return MemoryCategory.PERSON
    return MemoryCategory.OBJECT


def for_graph(category: MemoryCategory) -> MemoryCategory:
    """Map a category to its graph-storage form (Food → Preference)."""
    return _GRAPH_MAP.get(category, category)


# --- self-check ---
def _self_check() -> None:  # pragma: no cover
    assert classify("Person") is MemoryCategory.PERSON
    assert classify("Organization") is MemoryCategory.ORGANIZATION
    assert classify("Food") is MemoryCategory.FOOD
    assert classify("Bogus", name="Asep") is MemoryCategory.PERSON
    assert classify(None, name="a") is MemoryCategory.OBJECT
    assert for_graph(MemoryCategory.FOOD) is MemoryCategory.PREFERENCE
    assert for_graph(MemoryCategory.PERSON) is MemoryCategory.PERSON
    print("classifier self-check OK")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
