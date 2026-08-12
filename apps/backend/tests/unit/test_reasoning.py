"""Unit tests — reasoning: MemoraAgent tool generation + system prompt + Display.

Replaces the old GeminiLiveSession/ReasoningAgent/Speaker tests. The new
architecture uses LiveKit AgentSession + RealtimeModel, so there's no custom
session/speaker to test. We test:
  - System prompt content (unchanged)
  - MemoraAgent construction + tool generation
  - Display publish (unchanged)
  - Tool dispatch via _build_tools + registry
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from reasoning.agent.agent import MemoraAgent, _build_tools
from reasoning.prompts.system import build_system_instruction
from reasoning.response.display import _MAX_PAYLOAD, Display
from tools import ToolContext


class TestSystemPrompt:
    def test_static_instruction(self) -> None:
        filled = build_system_instruction("Orang: Asep. Lokasi: apotek.")
        base = build_system_instruction("")
        assert filled == base
        assert "{{context_package}}" not in filled

    def test_contains_face_identity_rules(self) -> None:
        base = build_system_instruction("")
        assert "Aturan identitas wajah" in base
        assert "Mungkin" in base
        assert "Orang tidak dikenali" in base
        assert "search_person" in base
        assert "register_face" in base

    def test_search_before_register_guidance(self) -> None:
        base = build_system_instruction("")
        assert "SELALU" in base and "search_person" in base and "register_person" in base


class TestMemoraAgent:
    def test_construct_agent(self) -> None:
        ctx = ToolContext()
        agent = MemoraAgent(tool_ctx=ctx)
        assert agent._tool_ctx is ctx
        assert agent._on_extract is None

    def test_construct_with_on_extract(self) -> None:
        ctx = ToolContext()

        async def _extract(text, sid):
            pass

        agent = MemoraAgent(tool_ctx=ctx, on_extract=_extract)
        assert agent._on_extract is _extract

    def test_build_tools_count_matches_declarations(self) -> None:
        from schemas import ALL_FUNCTION_DECLARATIONS

        ctx = ToolContext()
        tools = _build_tools(ctx)
        assert len(tools) == len(ALL_FUNCTION_DECLARATIONS)
        declared_names = {d["name"] for d in ALL_FUNCTION_DECLARATIONS}
        tool_names = {t.info.name for t in tools}
        assert tool_names == declared_names

    async def test_tool_dispatch_known_tool(self) -> None:
        """A generated tool should dispatch to the registry callable."""
        import tools.registry as reg

        async def _fake_firmware(args, ctx):
            return {"firmware_version": "test"}

        orig = reg.build_registry()
        reg._REGISTRY = {**orig, "firmware_version": _fake_firmware}
        try:
            ctx = ToolContext()
            agent = MemoraAgent(tool_ctx=ctx)
            dispatch = agent._dispatch("firmware_version")
            result = await dispatch({}, MagicMock())
            assert result == {"firmware_version": "test"}
        finally:
            reg._REGISTRY = orig

    async def test_tool_dispatch_unknown_tool(self) -> None:
        ctx = ToolContext()
        agent = MemoraAgent(tool_ctx=ctx)
        dispatch = agent._dispatch("nonexistent_tool")
        result = await dispatch({}, MagicMock())
        assert "unknown tool" in result["error"]

    async def test_tool_dispatch_error_caught(self) -> None:
        import tools.registry as reg

        async def _boom(args, ctx):
            raise ValueError("kaboom")

        orig = reg.build_registry()
        reg._REGISTRY = {**orig, "firmware_version": _boom}
        try:
            ctx = ToolContext()
            agent = MemoraAgent(tool_ctx=ctx)
            dispatch = agent._dispatch("firmware_version")
            result = await dispatch({}, MagicMock())
            assert "ValueError" in result["error"]
        finally:
            reg._REGISTRY = orig


class TestDisplay:
    async def test_publish(self) -> None:
        pub = AsyncMock()
        await Display(SimpleRoom(pub)).show("halo")
        pub.assert_awaited_once_with("halo", reliable=True, topic="display")

    async def test_empty_noop(self) -> None:
        pub = AsyncMock()
        await Display(SimpleRoom(pub)).show("")
        pub.assert_not_called()

    async def test_long_truncated(self) -> None:
        pub = AsyncMock()
        await Display(SimpleRoom(pub)).show("x" * 5000)
        sent = pub.await_args.args[0]
        assert len(sent) == _MAX_PAYLOAD


class SimpleRoom:
    def __init__(self, pub) -> None:
        self.local_participant = SimpleNamespace(publish_data=pub)
