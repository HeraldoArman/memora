"""Consolidator — write validated ExtractedKnowledge into Neo4j + Postgres.

memory_pipeline.md §7 (consolidation): create/update/merge/archive/conflict. For the
hackathon we implement CREATE (new entity/edge) + UPDATE (existing person gains edges) —
MERGE/ARCHIVE/CONFLICT need source-corroboration across sessions, out of scope. The graph
MERGEs on name, so re-mentioning an entity is idempotent (no duplicate nodes).

Writes:
- Person entities → PersonService.register_person (MERGE on person_id; new id if none).
- Non-person entities → KnowledgeService.upsert_entity (MERGE on name).
- Relationships → KnowledgeService.add_relation (Person→entity edge, MERGE).

A name→person_id map threads through so relationships link the right Person node.
"""

from __future__ import annotations

import logging

from constants import MemoryCategory, RelationshipType
from extraction.classifier import classify, for_graph
from extraction.normalizer import normalize
from extraction.resolver import resolve_name
from extraction.verifier import accepted, first_person_boost, verify
from services import KnowledgeService, MemoryService, PersonService

logger = logging.getLogger(__name__)

# Valid graph edge labels. LLM relationship strings are f-string'd into Cypher
# (queries.add_relation_cypher), so reject anything outside this set before it
# reaches the query builder — the schema enum constrains structured output, but
# the json.loads fallback in extractor._parse can bypass it.
_VALID_RELATIONSHIPS = {r.value for r in RelationshipType}


class Consolidator:
    """Write ExtractedKnowledge through the service layer into the stores."""

    def __init__(
        self,
        *,
        person_service: PersonService | None = None,
        knowledge_service: KnowledgeService | None = None,
        memory_service: MemoryService | None = None,
        text_embedder=None,
        text_index=None,
    ) -> None:
        self.person_service = person_service or PersonService()
        self.knowledge_service = knowledge_service or KnowledgeService()
        self.memory_service = memory_service or MemoryService()
        self.text_embedder = text_embedder
        self.text_index = text_index

    async def consolidate(
        self,
        extraction: dict,
        *,
        content: str = "",
        session_id: str | None = None,
    ) -> dict:
        """Consolidate one extraction result. Returns a summary dict.

        Verifies overall confidence first; REJECT → skip. Then resolves entities to graph
        nodes (registering Person ids), adds relationships, and persists the episode.
        """
        confidence = float(extraction.get("confidence", 0.0))
        level = verify(confidence, content=content)
        if not accepted(level):
            logger.info("extraction rejected (confidence=%.2f, level=%s)", confidence, level)
            return {"action": "reject", "level": level.value, "entities": 0, "relationships": 0}

        # Resolve + register entities. name→person_id for Person nodes.
        person_ids: dict[str, str] = {}
        entity_count = 0
        for ent in extraction.get("entities", []):
            raw_name = ent.get("name", "")
            if not raw_name:
                continue
            canonical = ent.get("canonical_name") or resolve_name(raw_name)
            category = classify(ent.get("category"), name=canonical)
            if category is MemoryCategory.PERSON:
                node = await self.person_service.register_person(name=canonical)
                pid = node.get("person_id")
                if pid:
                    person_ids[canonical] = pid
                entity_count += 1
            else:
                graph_cat = for_graph(category)
                await self.knowledge_service.upsert_entity(name=canonical, category=graph_cat.value)
                entity_count += 1

        # Add relationships. subject must resolve to a Person; register if not already.
        rel_count = 0
        for rel in extraction.get("relationships", []):
            subj = rel.get("subject", "")
            rel_type = rel.get("relationship", "")
            obj = rel.get("object", "")
            if not subj or not rel_type or not obj:
                continue
            # Security: rel_type is interpolated into Cypher as the edge label.
            # Drop unknown relationship types so LLM output (or the json.loads
            # fallback path) can't inject an arbitrary label into the query.
            if rel_type not in _VALID_RELATIONSHIPS:
                logger.warning("rejecting unknown relationship type %r", rel_type)
                continue
            subj_canon = resolve_name(subj)
            obj_canon = normalize(obj)
            if subj_canon not in person_ids:
                # relationship subject assumed Person; register to get an id
                node = await self.person_service.register_person(name=subj_canon)
                pid = node.get("person_id")
                if pid:
                    person_ids[subj_canon] = pid
            pid = person_ids.get(subj_canon)
            if not pid:
                continue
            # classify the object so the edge points at the right label
            obj_entity = next(
                (
                    e
                    for e in extraction.get("entities", [])
                    if resolve_name(e.get("name", "")) == obj_canon
                ),
                None,
            )
            obj_category = for_graph(
                classify(obj_entity.get("category") if obj_entity else None, name=obj_canon)
            )
            try:
                await self.knowledge_service.add_relation(
                    person_id=pid,
                    name=obj_canon,
                    category=obj_category.value,
                    relationship=rel_type,
                )
                rel_count += 1
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "add_relation failed (%s -[%s]-> %s): %s", subj_canon, rel_type, obj_canon, e
                )

        from uuid import UUID

        # Persist extracted fact statements (raw strings → memory_facts). Confidence is
        # per-fact: a first-person statement ("I'm Asep") gets the provenance boost, a
        # third-person one ("Asep works at Tokopedia") does not — applying the boost to the
        # whole turn over-credited facts the speaker wasn't asserting about themselves.
        # If exactly one person was identified in this extraction, tag all facts with them.
        # When no person is identified (unnamed conversation), facts are orphaned (person_id
        # = NULL) and later linked retroactively when the person is identified.
        facts = [str(f) for f in extraction.get("facts", [])]
        fact_count = 0
        if facts:
            fact_confidences = [first_person_boost(confidence, f) for f in facts]
            fact_person_id = next(iter(person_ids.values())) if len(person_ids) == 1 else None
            try:
                fact_count = await self.memory_service.add_facts(
                    facts=facts,
                    session_id=UUID(session_id) if session_id else None,
                    person_id=fact_person_id,
                    confidences=fact_confidences,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("fact persist failed: %s", e)

            # Embed facts into the text index for semantic retrieval (graceful if unwired)
            if self.text_embedder is not None and self.text_index is not None:
                try:
                    embeddings = await self.text_embedder.embed_batch(facts)
                    for fact_text, emb in zip(facts, embeddings, strict=False):
                        if emb is not None:
                            self.text_index.add(emb, fact_text)
                except Exception as e:  # noqa: BLE001
                    logger.warning("fact embedding failed: %s", e)

        return {
            "action": "create",
            "level": level.value,
            "entities": entity_count,
            "relationships": rel_count,
            "facts": fact_count,
            "person_ids": person_ids,
        }


# --- self-check: dry-run the verification gate with stubbed services ---
def _self_check() -> None:  # pragma: no cover
    # REJECT path: low confidence, no store calls
    from unittest.mock import AsyncMock

    c = Consolidator(
        person_service=AsyncMock(spec=PersonService),
        knowledge_service=AsyncMock(spec=KnowledgeService),
        memory_service=AsyncMock(spec=MemoryService),
    )
    import asyncio

    out = asyncio.run(
        c.consolidate({"confidence": 0.1, "entities": [], "relationships": []}, content="x")
    )
    assert out["action"] == "reject", out
    # ACCEPT path: confidence high, person registered + relation added
    c2 = Consolidator(
        person_service=AsyncMock(spec=PersonService),
        knowledge_service=AsyncMock(spec=KnowledgeService),
        memory_service=AsyncMock(spec=MemoryService),
    )
    c2.person_service.register_person = AsyncMock(return_value={"person_id": "pid1"})
    c2.knowledge_service.upsert_entity = AsyncMock(return_value={"name": "Tokopedia"})
    c2.knowledge_service.add_relation = AsyncMock(return_value={"name": "Tokopedia"})
    extraction = {
        "confidence": 0.95,
        "entities": [
            {"name": "Asep", "category": "Person"},
            {"name": "Tokopedia", "category": "Organization"},
            {"name": "sushi", "category": "Food"},
        ],
        "relationships": [
            {"subject": "Asep", "relationship": "WORKS_AT", "object": "Tokopedia"},
            {"subject": "Asep", "relationship": "LIKES", "object": "sushi"},
        ],
        "facts": ["Asep likes sushi", "Asep works at Tokopedia"],
    }
    c2.memory_service.add_facts = AsyncMock(return_value=2)
    out = asyncio.run(
        c2.consolidate(extraction, content="I'm Asep, I work at Tokopedia, I like sushi")
    )
    assert out["action"] == "create", out
    assert out["entities"] == 3, out
    assert out["relationships"] == 2, out
    assert out["person_ids"]["Asep"] == "pid1", out
    # sushi (Food) → Preference graph category
    assert c2.knowledge_service.upsert_entity.call_args_list[-1].kwargs["category"] == "Preference"
    # facts persisted with per-fact confidence (first-person boost applied per fact)
    assert out["facts"] == 2, out
    c2.memory_service.add_facts.assert_awaited_once()
    call = c2.memory_service.add_facts.await_args.kwargs
    assert call["facts"] == ["Asep likes sushi", "Asep works at Tokopedia"], call
    assert call["confidences"] == [0.95, 0.95], call  # neither fact is first-person
    assert "confidence" not in call or call.get("confidence") is None, call
    print(
        f"consolidator self-check OK: {out['entities']} entities, "
        f"{out['relationships']} rels, {out['facts']} facts"
    )


if __name__ == "__main__":  # pragma: no cover
    _self_check()
