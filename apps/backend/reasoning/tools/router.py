"""Tool router — dispatch Gemini Live tool_call events to tool callables.

Receives a LiveServerToolCall (function_calls list), resolves each by name through
the tool registry, runs the callable with the ToolContext, and returns a list of
FunctionResponse dicts matched by id for send_tool_response.

Ponytail: one function. The registry already maps name→callable; the router just
loops, runs, wraps. Failures become a FunctionResponse with an error dict so the
model can react, instead of crashing the session.
"""

from __future__ import annotations

import logging
from typing import Any

from google.genai import types

from tools import ToolContext, get_tool

log = logging.getLogger(__name__)


async def dispatch_tool_call(tool_call: Any, ctx: ToolContext) -> list[dict]:
    """Run every function call in a LiveServerToolCall; return FunctionResponse dicts.

    `tool_call.function_calls` is a list of FunctionCall(id, name, args). We run each
    concurrently-safe (sequential is fine — tools are I/O bound and short) and wrap
    the result. A tool that raises becomes {error: ...} so the model can recover.
    """
    out: list[dict] = []
    calls = getattr(tool_call, "function_calls", None) or []
    for call in calls:
        name = call.name
        cid = call.id
        args = dict(call.args or {})
        func = get_tool(name)
        if func is None:
            log.warning("tool not found: %s", name)
            out.append(_resp(cid, name, {"error": f"unknown tool: {name}"}))
            continue
        try:
            log.debug("tool dispatch: %s args=%s", name, args)
            result = await func(args, ctx)
            log.debug("tool result: %s -> %s", name, str(result)[:200])
        except Exception as e:  # noqa: BLE001 — tool errors must not kill the session
            log.exception("tool %s failed", name)
            result = {"error": f"{type(e).__name__}: {e}"}
        out.append(_resp(cid, name, result))
    return out


def _resp(call_id: str, name: str, result: dict) -> dict:
    """Build a FunctionResponse dict for send_tool_response."""
    return {"id": call_id, "name": name, "response": result}


# --- self-check: dispatch routes known + unknown tools ---
def _self_check() -> None:  # pragma: no cover
    import asyncio

    # build a fake tool_call with two function calls: one known, one unknown
    fc_known = types.FunctionCall(id="c1", name="firmware_version", args={})
    fc_unknown = types.FunctionCall(id="c2", name="nope", args={})
    tc = types.LiveServerToolCall(function_calls=[fc_known, fc_unknown])

    # patch registry to return a dummy for firmware_version (avoid real services)
    import tools.registry as reg

    async def _dummy(args, ctx):
        return {"firmware_version": "test"}

    orig = reg.build_registry()  # ensure lazily-built map exists before patching
    reg._REGISTRY = {**orig, "firmware_version": _dummy}
    try:
        ctx = ToolContext()
        resps = asyncio.run(dispatch_tool_call(tc, ctx))
    finally:
        reg._REGISTRY = orig

    assert len(resps) == 2
    assert resps[0]["id"] == "c1"
    assert resps[0]["response"]["firmware_version"] == "test"
    assert "unknown tool" in resps[1]["response"]["error"]
    print("router self-check OK: 2 calls dispatched (known + unknown)")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
