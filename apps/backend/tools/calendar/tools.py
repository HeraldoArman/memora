"""Calendar + shopping tools — events + shopping list management."""

from __future__ import annotations

from datetime import datetime

from tools.registry import ToolContext


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


async def create_event(args: dict, ctx: ToolContext) -> dict:
    title = args.get("title")
    if not title:
        return {"error": "title required"}
    starts_at = _parse_dt(args.get("starts_at"))
    if starts_at is None:
        return {"error": "starts_at required (ISO 8601)"}
    return await ctx.event_service.create(
        title=title,
        starts_at=starts_at,
        location=args.get("location"),
        description=args.get("description"),
    )


async def search_schedule(args: dict, ctx: ToolContext) -> dict:
    query = args.get("query")
    if query:
        return {"events": await ctx.event_service.search(query)}
    return {"events": await ctx.event_service.upcoming()}


async def shopping_list(args: dict, ctx: ToolContext) -> dict:
    action = args.get("action", "list")
    item = args.get("item")
    if action == "list":
        return {"items": await ctx.shopping_service.list_items()}
    if not item:
        return {"error": "item required for add/remove/check"}
    if action == "add":
        return await ctx.shopping_service.add(item)
    if action == "remove":
        return {"deleted": await ctx.shopping_service.remove(item)}
    if action == "check":
        return await ctx.shopping_service.check(item) or {"error": "item not found"}
    return {"error": f"unknown action: {action}"}


CALENDAR_TOOL_FUNCS = {
    "create_event": create_event,
    "search_schedule": search_schedule,
    "shopping_list": shopping_list,
}
