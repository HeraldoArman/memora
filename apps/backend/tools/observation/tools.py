"""Observation tools — expose live perception state to the agent.

refactor/bare-minimum: reads from ToolContext.last_face directly instead of
CurrentContext from WorkingMemory/ObservationEngine. Re-enable the observation
pipeline by switching back to current_context.
"""

from __future__ import annotations

from tools.registry import ToolContext


async def current_scene(args: dict, ctx: ToolContext) -> dict:
    s = ctx.last_scene
    if s is None or s.get("location") is None:
        return {"available": False, "location": None, "activity": None}
    return {
        "available": True,
        "location": s["location"],
        "objects": s.get("objects", []),
        "activity": s.get("activity"),
        "confidence": s.get("confidence", 0.8),
    }


async def visible_people(args: dict, ctx: ToolContext) -> dict:
    """List currently visible people by running face recognition on-demand."""
    await ctx.refresh_face()
    lf = ctx.last_face
    if lf is None:
        return {"available": False, "people": []}
    if lf.get("is_known") and lf.get("name"):
        return {"available": True, "people": [lf["name"]]}
    if lf.get("is_possible") and lf.get("name"):
        return {"available": True, "people": [f"Mungkin {lf['name']}"]}
    return {"available": True, "people": ["Orang tidak dikenali"]}


async def current_activity(args: dict, ctx: ToolContext) -> dict:
    s = ctx.last_scene
    if s is None or s.get("activity") is None:
        return {"available": False, "activity": None, "location": None}
    return {
        "available": True,
        "activity": s["activity"],
        "location": s.get("location"),
        "confidence": s.get("confidence", 0.8),
    }


async def conversation_summary(args: dict, ctx: ToolContext) -> dict:
    limit = args.get("limit", 10)
    episodes = await ctx.memory_service.recent_memories(limit=limit)
    return {"recent_sessions": episodes}


OBSERVATION_TOOL_FUNCS = {
    "current_scene": current_scene,
    "visible_people": visible_people,
    "current_activity": current_activity,
    "conversation_summary": conversation_summary,
}
