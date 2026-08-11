"""Person tools — search/identify/register/update people.

Gemini Live calls these by name; the router dispatches args here. Each returns a
JSON-serializable dict for send_tool_response. Tools are thin service callers — no business
logic here (that lives in services/).
"""

from __future__ import annotations

import logging

from tools.registry import ToolContext

log = logging.getLogger(__name__)


async def search_person(args: dict, ctx: ToolContext) -> dict:
    """Search any entity by name substring (graph)."""
    query = args.get("query", "")
    if not query:
        return {"error": "query required"}
    hits = await ctx.person_service.search_by_name(query)
    return {"results": hits}


async def get_person(args: dict, ctx: ToolContext) -> dict:
    """Get a person's full profile: name, notes, and relationships (LIKES, WORKS_AT, etc.)."""
    person_id = args.get("person_id")
    if not person_id:
        return {"error": "person_id required"}
    person = await ctx.person_service.get_person(person_id)
    if person is None:
        return {"error": "person not found"}
    return {"person": person}


async def search_person_by_face(args: dict, ctx: ToolContext) -> dict:
    """Identify the currently visible person via the face index.

    Uses the latest face observation's embedding from Working Memory (the recognizer already
    ran). If no face observation is available, returns unknown.
    """
    emb = ctx.current_face_embedding()
    if emb is None:
        return {"person_id": None, "known": False, "possible": False, "note": "no face detected"}
    return await ctx.person_service.search_by_face(emb)


async def register_person(args: dict, ctx: ToolContext) -> dict:
    """Register a new person by name.

    If a conversation session is active, retroactively links orphan facts (extracted
    before the person was identified) from this session to the new person_id — so
    facts like "suka sushi" said before the name was spoken are not lost.
    """
    name = args.get("name")
    if not name:
        return {"error": "name required"}
    node = await ctx.person_service.register_person(name=name)
    person_id = node.get("person_id")
    # Retroactively link orphan facts from the current conversation session to this person.
    if person_id and ctx.session_id:
        try:
            from uuid import UUID

            linked = await ctx.memory_service.link_facts_to_person(
                session_id=UUID(ctx.session_id), person_id=person_id
            )
            if linked:
                log.info("retroactively linked %d orphan fact(s) to %s", linked, person_id)
        except Exception:  # noqa: BLE001
            log.warning("retroactive fact link failed for %s", person_id)
    return {"person": node}


async def register_face(args: dict, ctx: ToolContext) -> dict:
    """Link the currently visible face to an existing person (enroll identity).

    Uses the latest face embedding from Working Memory (the recognizer already ran). The
    person must already exist (register_person first). FaceRepository.register is sync.
    """
    person_id = args.get("person_id")
    if not person_id:
        return {"error": "person_id required"}
    emb = ctx.current_face_embedding()
    if emb is None:
        return {"person_id": person_id, "enrolled": False, "note": "no face detected"}
    try:
        row = await ctx.person_service.register_face(emb, person_id)
    except RuntimeError as exc:  # face_repo not wired
        return {"person_id": person_id, "enrolled": False, "note": str(exc)}
    # Persist to Postgres (durable) + FAISS file (local cache). Postgres is the
    # source of truth across backend + worker containers; the .faiss file is a
    # local cache for dev/offline. Guarded so tests that stub the service don't crash.
    try:
        from postgres.repositories import FaceEmbeddingRepo
        from postgres.session import get_sessionmaker

        async with get_sessionmaker()() as db:
            await FaceEmbeddingRepo().save(db, person_id=person_id, embedding=emb)
    except Exception:  # noqa: BLE001 — DB unavailable shouldn't block enrollment
        log.warning("face embedding persist to DB failed for %s", person_id)
    return {"person_id": person_id, "enrolled": True, "face_index_row": row}


async def update_person(args: dict, ctx: ToolContext) -> dict:
    """Update a person's notes."""
    person_id = args.get("person_id")
    if not person_id:
        return {"error": "person_id required"}
    notes = args.get("notes")
    node = await ctx.person_service.update_person(person_id=person_id, notes=notes)
    if node is None:
        return {"error": "person not found"}
    return {"person": node}


# name → callable, for the registry.
PERSON_TOOL_FUNCS = {
    "search_person": search_person,
    "get_person": get_person,
    "search_person_by_face": search_person_by_face,
    "register_person": register_person,
    "register_face": register_face,
    "update_person": update_person,
}
