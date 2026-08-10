"""Packager — assemble a ContextPackage DTO from ranked memories + observation context.

context.md §11 (Context Package), §15 (provenance). Turns the ranker's scored candidates +
the current WorkingMemory snapshot (visible people, scene, device) + upcoming reminders into
the structured ContextPackage delivered to the reasoning agent's system instruction.
"""

from __future__ import annotations

from constants import MemoryCategory
from dto.memory import ContextPackage, Fact
from dto.observations import CurrentContext

_VALID_CATEGORIES = {c.value for c in MemoryCategory}


def package(
    *,
    ranked: list[tuple[dict, float, dict]],
    current: CurrentContext | None = None,
    reminders: list[str] | None = None,
    conversation_history: list[str] | None = None,
    user_question: str | None = None,
    top_k: int = 10,
) -> ContextPackage:
    """Build a ContextPackage from the top-k ranked memory candidates.

    Each candidate's content becomes a Fact with its signal scores as provenance.
    """
    facts: list[Fact] = []
    provenance: dict[str, dict] = {}
    for cand, score, signals in ranked[:top_k]:
        content = cand.get("content") or ""
        if not content:
            continue
        cat = cand.get("category")
        # coerce to a valid MemoryCategory; graph labels (Person/Organization/...) map directly,
        # episodic/unknown labels fall back to a neutral category.
        if cat and cat in _VALID_CATEGORIES:
            category = MemoryCategory(cat)
        else:
            category = MemoryCategory.OBJECT
        fact = Fact(
            subject=content,
            statement=content,
            category=category,
            confidence=score,
        )
        facts.append(fact)
        provenance[fact.fact_id] = {
            "source": cand.get("source"),
            "source_id": cand.get("source_id"),
            "score": round(score, 4),
            "signals": signals,
        }
    return ContextPackage(
        location=current.scene if current else None,
        visible_people=current.visible_people if current else [],
        relevant_facts=facts,
        conversation_history=conversation_history or [],
        upcoming_reminders=reminders or [],
        user_question=user_question,
        device_context=current.device if current else None,
        provenance=provenance,
    )


def to_text(pkg: ContextPackage, *, activity: str | None = None) -> str:
    """Render a ContextPackage as the text injected into the system instruction.

    Bahasa Indonesia, compact. This is what replaces {{context_package}} at connect time.
    `activity` is passed separately (ContextPackage has no activity field) from the
    CurrentContext that produced the package.
    """
    lines: list[str] = []
    if pkg.location:
        lines.append(f"Lokasi: {pkg.location}")
    if pkg.visible_people:
        lines.append("Orang terlihat: " + ", ".join(pkg.visible_people))
    if activity:
        lines.append(f"Aktivitas: {activity}")
    if pkg.relevant_facts:
        lines.append("Fakta diketahui:")
        for f in pkg.relevant_facts:
            lines.append(f"- {f.statement}")
    if pkg.upcoming_reminders:
        lines.append("Pengingat: " + "; ".join(pkg.upcoming_reminders))
    if pkg.conversation_history:
        lines.append("Riwayat: " + " | ".join(pkg.conversation_history[-5:]))
    if pkg.user_question:
        lines.append(f"Pertanyaan: {pkg.user_question}")
    if pkg.device_context:
        lines.append(f"Perangkat: {pkg.device_context}")
    return "\n".join(lines) if lines else "(belum ada konteks)"


# --- self-check ---
def _self_check() -> None:  # pragma: no cover
    ranked = [
        (
            {
                "content": "Asep works at Tokopedia",
                "category": "Person",
                "source": "neo4j",
                "source_id": "pid1",
            },
            0.85,
            {"semantic": 0.4},
        ),
        (
            {
                "content": "met Asep",
                "category": "Episodic",
                "source": "postgres",
                "source_id": "s1",
            },
            0.60,
            {"temporal": 0.9},
        ),
    ]
    ctx = CurrentContext(visible_people=["Asep"], scene="apotek", device="baterai 72%")
    pkg = package(
        ranked=ranked, current=ctx, reminders=["beli obat 15:00"], user_question="Siapa ini?"
    )
    assert len(pkg.relevant_facts) == 2, pkg.relevant_facts
    assert pkg.visible_people == ["Asep"]
    assert pkg.location == "apotek"
    assert pkg.user_question == "Siapa ini?"
    assert "beli obat 15:00" in pkg.upcoming_reminders
    assert pkg.provenance  # provenance populated
    # Person label → Person category; "Episodic" (not a MemoryCategory) → Object fallback
    assert pkg.relevant_facts[0].category is MemoryCategory.PERSON
    assert pkg.relevant_facts[1].category is MemoryCategory.OBJECT
    txt = to_text(pkg)
    assert "Asep works at Tokopedia" in txt
    assert "apotek" in txt
    assert "Siapa ini?" in txt
    print(f"packager self-check OK: {len(pkg.relevant_facts)} facts, text={len(txt)} chars")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
