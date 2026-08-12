"""MemoraAgent — LiveKit Agent subclass with Gemini RealtimeModel tools.

Replaces the custom GeminiLiveSession + ReasoningAgent + ToolRouter with a
single Agent class. Audio, video, reconnection, VAD-based turn detection, and
audio output are handled by AgentSession + RealtimeModel — no custom plumbing.

Tools are auto-generated from ALL_FUNCTION_DECLARATIONS via raw_schema, so
every declared tool gets a @function_tool wrapper that dispatches to the
existing registry callable. No per-tool boilerplate.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from livekit.agents import Agent, RunContext, function_tool

from prompts import SYSTEM_INSTRUCTION
from tools import ToolContext, build_registry

log = logging.getLogger(__name__)


class MemoraAgent(Agent):
    """LiveKit Agent for Memora — dementia memory assistant.

    Tools are exposed via @function_tool(raw_schema=...) auto-generated from
    ALL_FUNCTION_DECLARATIONS. The agent sees video directly (via
    RoomOptions.video_input=True) and hears audio directly (via AgentSession).
    InsightFace runs in parallel for face recognition, writing results to
    tool_ctx.last_face.
    """

    def __init__(
        self,
        *,
        tool_ctx: ToolContext,
        on_extract: Callable[[str, str | None], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(instructions=SYSTEM_INSTRUCTION)
        self._tool_ctx = tool_ctx
        self._on_extract = on_extract
        log.info(
            "MemoraAgent constructed: instructions=%d chars, tool_ctx=%s, on_extract=%s",
            len(SYSTEM_INSTRUCTION),
            "wired" if tool_ctx else "None",
            "wired" if on_extract else "None",
        )

    async def on_enter(self) -> None:
        """Called when agent becomes active. Greet the user."""
        log.info("on_enter: agent becoming active, generating greeting...")
        await self.session.generate_reply(
            instructions="Sapa pengguna dengan singkat dalam Bahasa Indonesia."
        )
        log.info("on_enter: greeting generated")

    # --- Tool dispatch ---

    def _dispatch(self, name: str) -> Callable[[dict, RunContext], Awaitable[Any]]:
        """Return a handler that forwards raw_arguments to the registry callable."""
        registry = build_registry()

        async def _handler(raw_arguments: dict[str, object], ctx: RunContext) -> Any:
            log.info("tool call: %s args=%s", name, dict(raw_arguments))
            func = registry.get(name)
            if func is None:
                log.error("tool not found in registry: %s", name)
                return {"error": f"unknown tool: {name}"}
            try:
                result = await func(dict(raw_arguments), self._tool_ctx)
                log.info(
                    "tool result: %s → %s",
                    name,
                    str(result)[:300] if result else "None",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("tool %s failed: %s", name, exc, exc_info=True)
                return {"error": f"{type(exc).__name__}: {exc}"}
            return result

        return _handler


def _build_tools(tool_ctx: ToolContext, on_extract=None) -> list:
    """Auto-generate @function_tool wrappers from ALL_FUNCTION_DECLARATIONS.

    Each declared tool gets a raw_schema function_tool that dispatches to the
    existing registry callable. This avoids writing 31 wrapper methods by hand.
    """
    from schemas import ALL_FUNCTION_DECLARATIONS

    log.info(
        "building tools from ALL_FUNCTION_DECLARATIONS: %d declarations",
        len(ALL_FUNCTION_DECLARATIONS),
    )
    agent = MemoraAgent(tool_ctx=tool_ctx, on_extract=on_extract)
    tools = []
    for decl in ALL_FUNCTION_DECLARATIONS:
        name = decl["name"]
        handler = agent._dispatch(name)

        schema = {
            "name": name,
            "description": decl.get("description", ""),
            "parameters": decl.get("parameters", {"type": "object", "properties": {}}),
        }
        tool = function_tool(handler, raw_schema=schema)
        tools.append(tool)

    log.info("built %d @function_tool wrappers", len(tools))
    return tools


# --- self-check: tool count matches declarations ---
def _self_check() -> None:  # pragma: no cover
    from schemas import ALL_FUNCTION_DECLARATIONS

    ctx = ToolContext()
    tools = _build_tools(ctx)
    declared = {d["name"] for d in ALL_FUNCTION_DECLARATIONS}
    tool_names = {t.info.name for t in tools}
    assert tool_names == declared, f"mismatch: {tool_names ^ declared}"
    assert len(tools) == len(ALL_FUNCTION_DECLARATIONS)
    print(f"agent self-check OK: {len(tools)} tools generated from {len(declared)} declarations")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
