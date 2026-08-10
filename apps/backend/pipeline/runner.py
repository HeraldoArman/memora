"""Pipeline runner — orchestrate filter→extract→resolve→classify→verify→consolidate.

memory_pipeline.md §1–7. Async, event-triggered (by the ObservationEngine on a fused
CurrentContext with substantive speech, or by end-of-turn). This module is the single
entry point that turns a piece of conversation text into graph + episodic records.

    uv run python -m pipeline.runner

Phase 4 verify: synthetic "I'm Asep, I work at Tokopedia, I like sushi" → Neo4j
Person:Asep with WORKS_AT+LIKES edges + a Postgres episodic message.
"""

from __future__ import annotations

import logging

from extraction.extractor import KnowledgeExtractor
from pipeline.consolidator import Consolidator
from pipeline.filter import should_extract

logger = logging.getLogger(__name__)


class PipelineRunner:
    """Run the full extraction→consolidation chain over conversation text."""

    def __init__(
        self,
        *,
        extractor: KnowledgeExtractor | None = None,
        consolidator: Consolidator | None = None,
    ) -> None:
        self.extractor = extractor or KnowledgeExtractor()
        self.consolidator = consolidator or Consolidator()

    async def run(self, content: str, *, session_id: str | None = None) -> dict:
        """Extract + consolidate `content`. Returns the consolidator summary.

        Filter-rejected content → no extraction call, returns a skip summary.
        """
        if not should_extract(content):
            logger.info("pipeline skip (filtered): %r", content[:80])
            return {"action": "skip", "reason": "filtered", "entities": 0, "relationships": 0}
        logger.info("pipeline extract: session=%s content=%r", session_id, content[:80])
        extraction = await self.extractor.extract(content)
        logger.info(
            "pipeline extraction: %d entity(ies), %d relationship(s), conf=%.2f",
            len(extraction.get("entities", [])),
            len(extraction.get("relationships", [])),
            float(extraction.get("confidence", 0.0)),
        )
        summary = await self.consolidator.consolidate(
            extraction, content=content, session_id=session_id
        )
        logger.info("pipeline consolidate: %s", summary)
        return summary


# --- __main__: Phase 4 verification ---
async def _verify() -> None:  # pragma: no cover
    """Synthetic round-trip: "I'm Asep, I work at Tokopedia, I like sushi"."""
    from env import get_settings
    from graph import client as neo4j_client
    from graph import repository as graph_repo

    from postgres import session as pg_session
    from services import MemoryService

    settings = get_settings()
    pg_session.init_engine(settings.database_url)
    await neo4j_client.init_driver(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)

    # Start a conversation session to tie the episode to.
    mem = MemoryService()
    sid = await mem.start_session(summary="phase 4 verify")
    print(f"session: {sid}")

    # Real Gemini call when a key is configured; else a deterministic mock extractor so the
    # full pipeline→stores path is exercised without an external API dependency. The LLM
    # call shape is verified by extraction.extractor's offline self-check; this verifies the
    # wiring (filter→consolidate→Neo4j+Postgres).
    text = "I'm Asep, I work at Tokopedia, I like sushi"
    extractor = None
    if settings.gemini_api_key and settings.gemini_api_key != "dummy":
        extractor = KnowledgeExtractor()
    else:
        print("GEMINI_API_KEY is 'dummy' — using mock extractor for live DB verification")

        class _MockExtractor:
            async def extract(self, content: str) -> dict:  # noqa: D102
                return {
                    "entities": [
                        {"name": "Asep", "category": "Person", "canonical_name": "Asep"},
                        {"name": "Tokopedia", "category": "Organization"},
                        {"name": "sushi", "category": "Food"},
                    ],
                    "relationships": [
                        {"subject": "Asep", "relationship": "WORKS_AT", "object": "Tokopedia"},
                        {"subject": "Asep", "relationship": "LIKES", "object": "sushi"},
                    ],
                    "facts": ["Asep works at Tokopedia", "Asep likes sushi"],
                    "confidence": 0.95,
                }

        extractor = _MockExtractor()

    runner = PipelineRunner(extractor=extractor)
    summary = await runner.run(text, session_id=sid)
    print(f"pipeline summary: {summary}")

    # Verify Neo4j: Person:Asep with WORKS_AT→Tokopedia + LIKES→Sushi(Preference) edges.
    person_repo = graph_repo.PersonRepo()
    kg = graph_repo.KnowledgeGraphRepo()
    # find the Asep node we just created
    hits = await kg.search_entity("Asep")
    asep = next((h for h in hits if h.get("label") == "Person" and h.get("name") == "Asep"), None)
    assert asep is not None, f"Person:Asep not found in graph; hits={hits}"
    pid = asep["person_id"]
    print(f"neo4j: Person:Asep found (person_id={pid[:8]})")
    profile = await person_repo.get_person(pid)
    rels = profile.get("relationships", []) if profile else []
    rel_types = {(r.get("type"), r.get("target")) for r in rels}
    assert ("WORKS_AT", "Tokopedia") in rel_types, f"WORKS_AT→Tokopedia missing; rels={rels}"
    assert any(t == "LIKES" for t, _ in rel_types), f"LIKES edge missing; rels={rels}"
    print(f"neo4j edges: {sorted(str(t) for t in rel_types)}")

    # Verify Postgres: an episodic message was persisted under the session.
    from uuid import UUID

    msgs = await mem.conversation_history(UUID(sid))
    assert any("Tokopedia" in m["content"] for m in msgs), f"episodic message missing; msgs={msgs}"
    print(f"postgres: {len(msgs)} episodic message(s) persisted")

    await pg_session.close_engine()
    await neo4j_client.close_driver()
    print("\nPHASE 4 OK: extraction pipeline wrote graph + episodic records")


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys
    from pathlib import Path

    # Ensure backend packages importable when run as `python -m pipeline.runner`.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    asyncio.run(_verify())
