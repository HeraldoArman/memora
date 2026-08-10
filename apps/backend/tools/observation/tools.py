"""Observation tools — expose the current Working Memory snapshot to the agent.

These return the live CurrentContext fields. The agent calls current_scene / visible_people
etc. to get fresh perception data (dynamic context via tool-call results, not the system
prompt — arch decision #2).
"""

from __future__ import annotations

from tools.registry import ToolContext


def _ctx(ctx: ToolContext) -> dict:
    c = ctx.current_context
    if c is None:
        return {"available": False, "note": "no current observation context"}
    return {
        "available": True,
        "scene": c.scene,
        "activity": c.activity,
        "visible_people": c.visible_people,
        "device": c.device,
        "speech": getattr(c, "speech", None),
    }


async def current_scene(args: dict, ctx: ToolContext) -> dict:
    c = ctx.current_context
    if c is None:
        return {"available": False}
    return {"location": c.scene, "activity": c.activity, "confidence": c.confidence}


async def visible_people(args: dict, ctx: ToolContext) -> dict:
    c = ctx.current_context
    if c is None:
        return {"available": False, "people": []}
    return {"available": True, "people": c.visible_people}


async def current_activity(args: dict, ctx: ToolContext) -> dict:
    c = ctx.current_context
    if c is None:
        return {"available": False}
    return {"activity": c.activity, "location": c.scene}


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
