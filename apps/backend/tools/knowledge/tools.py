"""Knowledge tools — read the Neo4j knowledge graph (entities, relationships, preferences).

Thin service callers like the other tool modules; graph reads live in KnowledgeService /
PersonService. Wired into the registry by tools/registry.build_registry.
"""

from __future__ import annotations

from tools.registry import ToolContext


async def search_entity(args: dict, ctx: ToolContext) -> dict:
    """Search any entity in the knowledge graph by name substring."""
    query = args.get("query", "")
    if not query:
        return {"error": "query required"}
    return {"results": await ctx.knowledge_service.search_entity(query)}


async def entity_relationships(args: dict, ctx: ToolContext) -> dict:
    """Return the subgraph (nodes + edges) around an entity."""
    entity = args.get("entity", "")
    if not entity:
        return {"error": "entity required"}
    return await ctx.knowledge_service.entity_relationships(entity)


async def search_preferences(args: dict, ctx: ToolContext) -> dict:
    """Return stored preferences for a person."""
    person_id = args.get("person_id", "")
    if not person_id:
        return {"error": "person_id required"}
    return {"preferences": await ctx.knowledge_service.preferences(person_id)}


async def related_people(args: dict, ctx: ToolContext) -> dict:
    """Return people related to a person via the graph."""
    person_id = args.get("person_id", "")
    if not person_id:
        return {"error": "person_id required"}
    return {"related": await ctx.person_service.related_people(person_id)}


async def knowledge_graph(args: dict, ctx: ToolContext) -> dict:
    """Subgraph around an entity (alias of entity_relationships)."""
    entity = args.get("entity", "")
    if not entity:
        return {"error": "entity required"}
    return await ctx.knowledge_service.entity_relationships(entity)


# name → callable, for the registry.
KNOWLEDGE_TOOL_FUNCS = {
    "search_entity": search_entity,
    "entity_relationships": entity_relationships,
    "search_preferences": search_preferences,
    "related_people": related_people,
    "knowledge_graph": knowledge_graph,
}
