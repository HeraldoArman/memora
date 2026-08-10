"""Context Engine — build a ContextPackage for the reasoning agent.

context.md §1–13. The engine ties retrieval → ranking → summarization → packaging into one
`build()` call. Called by the ReasoningAgent before it sends the prepared context package to
Gemini Live (the live session receives only the prepared package, never raw storage).

Event-driven: the agent calls build() when a turn starts (user question) or a notable
context change (new person appears). The engine is stateless between calls — each build()
reads fresh from the stores + the passed CurrentContext.
"""

from __future__ import annotations

import logging

from context.packager import package, to_text
from context.summarizer import Summarizer
from dto.memory import ContextPackage
from dto.observations import CurrentContext
from memory.ranking.ranker import rank
from memory.retrieval.retriever import Retriever
from services import ReminderService

logger = logging.getLogger(__name__)


class ContextEngine:
    """Assemble a context package from memory + the current observation snapshot."""

    def __init__(
        self,
        *,
        retriever: Retriever | None = None,
        summarizer: Summarizer | None = None,
        reminder_service: ReminderService | None = None,
    ) -> None:
        self.retriever = retriever or Retriever()
        self.summarizer = summarizer or Summarizer()
        self.reminder_service = reminder_service or ReminderService()

    async def build(
        self,
        current: CurrentContext | None = None,
        *,
        user_question: str | None = None,
        conversation_history: list[str] | None = None,
        top_k: int = 10,
    ) -> tuple[ContextPackage, str]:
        """Return (ContextPackage, rendered_text) for the reasoning agent.

        Retrieves candidates from the graph + episodic store, ranks them against the query
        (user_question or the latest speech), folds in upcoming reminders, packages the
        result, and summarizes the rendered text if it exceeds the budget.
        """
        query = user_question or (current.speech if current else "") or ""
        visible = current.visible_people if current else []
        location = current.scene if current else None

        candidates = await self.retriever.retrieve(query, visible_people=visible)
        ranked = rank(candidates, query=query, visible_people=visible, location=location)

        # Upcoming reminders as plain strings for the package.
        reminders: list[str] = []
        try:
            upcoming = await self.reminder_service.upcoming(limit=5)
            reminders = [
                f"{r['title']} ({r['due_at']})" if r.get("due_at") else r["title"]
                for r in upcoming
                if not r.get("completed")
            ]
        except Exception as e:  # noqa: BLE001
            logger.warning("reminder fetch failed, continuing without: %s", e)

        pkg = package(
            ranked=ranked,
            current=current,
            reminders=reminders,
            conversation_history=conversation_history,
            user_question=user_question,
            top_k=top_k,
        )
        text = to_text(pkg, activity=current.activity if current else None)
        text = await self.summarizer.summarize(text)
        return pkg, text


# --- __main__: Phase 5 verification ---
async def _verify() -> None:  # pragma: no cover
    """Given seeded memories + visible_person:Asep, print the assembled package."""
    from env import get_settings
    from graph import client as neo4j_client

    from postgres import session as pg_session

    settings = get_settings()
    pg_session.init_engine(settings.database_url)
    await neo4j_client.init_driver(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)

    engine = ContextEngine()
    ctx = CurrentContext(visible_people=["Asep"], scene="apotek", speech="Siapa ini?")
    pkg, text = await engine.build(ctx, user_question="Siapa ini?")

    print("=== ContextPackage ===")
    print(f"location: {pkg.location}")
    print(f"visible_people: {pkg.visible_people}")
    print(f"facts: {len(pkg.relevant_facts)}")
    for f in pkg.relevant_facts:
        print(f"  - {f.statement} (score={f.confidence:.3f}, cat={f.category})")
    print(f"provenance entries: {len(pkg.provenance)}")
    print("\n=== Rendered text ===")
    print(text)

    await pg_session.close_engine()
    await neo4j_client.close_driver()
    print("\nPHASE 5 OK: context package assembled")


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    asyncio.run(_verify())
