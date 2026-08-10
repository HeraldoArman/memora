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
    """Ponytail: same as search_memory (no embedding-based similarity yet)."""
    return await search_memory(args, ctx)


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
