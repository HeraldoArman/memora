"""Reminder tools — create/update/delete/search/today reminders."""

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


async def create_reminder(args: dict, ctx: ToolContext) -> dict:
    title = args.get("title")
    if not title:
        return {"error": "title required"}
    due_at = _parse_dt(args.get("due_at"))
    note = args.get("note")
    return await ctx.reminder_service.create(title=title, due_at=due_at, note=note)


async def update_reminder(args: dict, ctx: ToolContext) -> dict:
    rid = args.get("reminder_id")
    if not rid:
        return {"error": "reminder_id required"}
    from uuid import UUID

    out = await ctx.reminder_service.update(
        UUID(rid),
        title=args.get("title"),
        note=args.get("note"),
        due_at=_parse_dt(args.get("due_at")),
        completed=args.get("completed"),
    )
    return out if out is not None else {"error": "reminder not found"}


async def delete_reminder(args: dict, ctx: ToolContext) -> dict:
    rid = args.get("reminder_id")
    if not rid:
        return {"error": "reminder_id required"}
    from uuid import UUID

    ok = await ctx.reminder_service.delete(UUID(rid))
    return {"deleted": ok}


async def search_reminders(args: dict, ctx: ToolContext) -> dict:
    query = args.get("query", "")
    if not query:
        return {"error": "query required"}
    return {"reminders": await ctx.reminder_service.search(query)}


async def today_reminders(args: dict, ctx: ToolContext) -> dict:
    return {"reminders": await ctx.reminder_service.today()}


REMINDER_TOOL_FUNCS = {
    "create_reminder": create_reminder,
    "update_reminder": update_reminder,
    "delete_reminder": delete_reminder,
    "search_reminders": search_reminders,
    "today_reminders": today_reminders,
}
