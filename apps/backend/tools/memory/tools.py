"""Memory tools — search/recall episodic + semantic memories."""

from __future__ import annotations

from tools.registry import ToolContext


async def search_memory(args: dict, ctx: ToolContext) -> dict:
    """Search memories: graph entities by name + episodic session summaries."""
    query = args.get("query", "")
    if not query:
        return {"error": "query required"}
    entities = await ctx.knowledge_service.search_entity(query)
    recent = await ctx.memory_service.recent_memories(limit=20)
    return {"entities": entities, "episodes": recent}


async def recent_memories(args: dict, ctx: ToolContext) -> dict:
    limit = args.get("limit", 10)
    return {"episodes": await ctx.memory_service.recent_memories(limit=limit)}


async def similar_memories(args: dict, ctx: ToolContext) -> dict:
    """Memories similar to a query: retrieve graph + episodic candidates, rank by overlap.

    Uses the same Retriever + ranker as the ContextEngine (token-overlap similarity —
    no embedding model call per query; deterministic at this scale).
    """
    query = args.get("query", "")
    if not query:
        return {"error": "query required"}
    from memory.ranking.ranker import rank
    from memory.retrieval.retriever import Retriever

    try:
        candidates = await Retriever().retrieve(query, visible_people=None)
        ranked = rank(candidates, query=query)
    except Exception as e:  # noqa: BLE001 — retrieval must not hard-fail a tool call
        return {"results": [], "note": f"retrieval failed: {e}"}
    return {
        "results": [
            {"content": c[0].get("content", ""), "score": round(c[1], 3)} for c in ranked[:10]
        ]
    }


async def memory_timeline(args: dict, ctx: ToolContext) -> dict:
    """Timeline of recent episodic sessions, optionally filtered to a person."""
    person_id = args.get("person_id")
    episodes = await ctx.memory_service.recent_memories(limit=50)
    if person_id:
        # ponytail: filter client-side; no per-person session index yet
        episodes = [e for e in episodes if person_id in str(e)]
    return {"timeline": episodes}


MEMORY_TOOL_FUNCS = {
    "search_memory": search_memory,
    "recent_memories": recent_memories,
    "similar_memories": similar_memories,
    "memory_timeline": memory_timeline,
}
