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
from unittest.mock import AsyncMock, MagicMock, PropertyMock

from reasoning.agent.agent import MemoraAgent, _build_tools
from reasoning.prompts.system import build_system_instruction
from reasoning.response.display import _MAX_PAYLOAD, Display
from tools import ToolContext


class TestSystemPrompt:
    def test_context_injected(self) -> None:
        filled = build_system_instruction("Orang: Asep. Lokasi: apotek.")
        base = build_system_instruction("")
        assert "Orang: Asep" in filled
        assert "Orang: Asep" not in base
        assert "{{context_package}}" not in filled

    def test_empty_context_shows_fallback(self) -> None:
        base = build_system_instruction("")
        assert "(belum ada konteks)" in base
        assert "{{context_package}}" not in base

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

    def test_construct_with_context_engine(self) -> None:
        ctx = ToolContext()
        engine = MagicMock()
        agent = MemoraAgent(tool_ctx=ctx, context_engine=engine)
        assert agent._context_engine is engine

    async def test_on_enter_calls_update_instructions(self) -> None:
        ctx = ToolContext()
        engine = AsyncMock()
        engine.build = AsyncMock(return_value=(None, "Fakta: Asep suka sushi"))
        agent = MemoraAgent(tool_ctx=ctx, context_engine=engine)
        agent.update_instructions = AsyncMock()
        mock_session = AsyncMock()
        mock_session.generate_reply = AsyncMock()
        type(agent).session = PropertyMock(return_value=mock_session)
        try:
            await agent.on_enter()
            agent.update_instructions.assert_awaited_once()
            instructions = agent.update_instructions.await_args.args[0]
            assert "Asep suka sushi" in instructions
        finally:
            del type(agent).session

    async def test_on_enter_skips_empty_context(self) -> None:
        ctx = ToolContext()
        engine = AsyncMock()
        engine.build = AsyncMock(return_value=(None, "(belum ada konteks)"))
        agent = MemoraAgent(tool_ctx=ctx, context_engine=engine)
        agent.update_instructions = AsyncMock()
        mock_session = AsyncMock()
        mock_session.generate_reply = AsyncMock()
        type(agent).session = PropertyMock(return_value=mock_session)
        try:
            await agent.on_enter()
            agent.update_instructions.assert_not_awaited()
        finally:
            del type(agent).session

    async def test_on_enter_no_context_engine(self) -> None:
        ctx = ToolContext()
        agent = MemoraAgent(tool_ctx=ctx)
        mock_session = AsyncMock()
        mock_session.generate_reply = AsyncMock()
        type(agent).session = PropertyMock(return_value=mock_session)
        try:
            await agent.on_enter()
            mock_session.generate_reply.assert_awaited_once()
        finally:
            del type(agent).session

    async def test_on_enter_context_build_exception_keeps_static(self) -> None:
        ctx = ToolContext()
        engine = AsyncMock()
        engine.build = AsyncMock(side_effect=RuntimeError("DB down"))
        agent = MemoraAgent(tool_ctx=ctx, context_engine=engine)
        agent.update_instructions = AsyncMock()
        mock_session = AsyncMock()
        mock_session.generate_reply = AsyncMock()
        type(agent).session = PropertyMock(return_value=mock_session)
        try:
            await agent.on_enter()
            agent.update_instructions.assert_not_awaited()
            mock_session.generate_reply.assert_awaited_once()
        finally:
            del type(agent).session

    async def test_on_enter_builds_context_from_last_face(self) -> None:
        ctx = ToolContext()
        ctx.last_face = {
            "name": "Asep",
            "person_id": "p1",
            "is_known": True,
            "embedding": None,
        }
        engine = AsyncMock()
        engine.build = AsyncMock(return_value=(None, "Orang terlihat: Asep"))
        agent = MemoraAgent(tool_ctx=ctx, context_engine=engine)
        agent.update_instructions = AsyncMock()
        mock_session = AsyncMock()
        mock_session.generate_reply = AsyncMock()
        type(agent).session = PropertyMock(return_value=mock_session)
        try:
            await agent.on_enter()
            # ContextEngine.build should have been called with CurrentContext
            # containing visible_people=["Asep"]
            build_args = engine.build.await_args
            current = build_args.args[0]
            assert "Asep" in current.visible_people
        finally:
            del type(agent).session

    async def test_on_enter_no_face_empty_visible(self) -> None:
        ctx = ToolContext()
        engine = AsyncMock()
        engine.build = AsyncMock(return_value=(None, "(belum ada konteks)"))
        agent = MemoraAgent(tool_ctx=ctx, context_engine=engine)
        agent.update_instructions = AsyncMock()
        mock_session = AsyncMock()
        mock_session.generate_reply = AsyncMock()
        type(agent).session = PropertyMock(return_value=mock_session)
        try:
            await agent.on_enter()
            build_args = engine.build.await_args
            current = build_args.args[0]
            assert current.visible_people == []
        finally:
            del type(agent).session

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


class TestProactivePlannerWiring:
    """Step 4: ProactivePlanner wiring in MemoraAgent."""

    def test_construct_with_planner(self) -> None:
        ctx = ToolContext()
        planner = MagicMock()
        agent = MemoraAgent(tool_ctx=ctx, planner=planner)
        assert agent._planner is planner

    def test_construct_no_planner(self) -> None:
        ctx = ToolContext()
        agent = MemoraAgent(tool_ctx=ctx)
        assert agent._planner is None

    async def test_on_enter_starts_planner(self) -> None:
        ctx = ToolContext()
        planner = MagicMock()
        planner.start = MagicMock()
        agent = MemoraAgent(tool_ctx=ctx, planner=planner)
        mock_session = AsyncMock()
        mock_session.generate_reply = AsyncMock()
        type(agent).session = PropertyMock(return_value=mock_session)
        try:
            await agent.on_enter()
            assert planner.start.called
            args = planner.start.call_args.args
            assert len(args) == 2
            assert callable(args[0])
            assert callable(args[1])
        finally:
            del type(agent).session

    async def test_on_enter_no_planner_no_crash(self) -> None:
        ctx = ToolContext()
        agent = MemoraAgent(tool_ctx=ctx)
        mock_session = AsyncMock()
        mock_session.generate_reply = AsyncMock()
        type(agent).session = PropertyMock(return_value=mock_session)
        try:
            await agent.on_enter()
            mock_session.generate_reply.assert_awaited_once()
        finally:
            del type(agent).session

    def test_get_context_none_when_empty(self) -> None:
        ctx = ToolContext()
        agent = MemoraAgent(tool_ctx=ctx)
        assert agent._get_context() is None

    def test_get_context_from_face_and_scene(self) -> None:
        ctx = ToolContext()
        ctx.last_face = {
            "name": "Asep",
            "is_known": True,
            "embedding": None,
        }
        ctx.last_scene = {"location": "apotek", "activity": "beli obat"}
        agent = MemoraAgent(tool_ctx=ctx)
        current = agent._get_context()
        assert current is not None
        assert "Asep" in current.visible_people
        assert current.scene == "apotek"
        assert current.activity == "beli obat"

    def test_get_context_unknown_face(self) -> None:
        ctx = ToolContext()
        ctx.last_face = {
            "name": None,
            "is_known": False,
            "is_possible": False,
            "embedding": None,
        }
        agent = MemoraAgent(tool_ctx=ctx)
        current = agent._get_context()
        assert current is not None
        assert "Orang tidak dikenali" in current.visible_people

    def test_get_context_possible_match(self) -> None:
        ctx = ToolContext()
        ctx.last_face = {
            "name": "Budi",
            "is_known": False,
            "is_possible": True,
            "embedding": None,
        }
        agent = MemoraAgent(tool_ctx=ctx)
        current = agent._get_context()
        assert current is not None
        assert "Mungkin Budi" in current.visible_people

    def test_get_context_scene_only_no_face(self) -> None:
        ctx = ToolContext()
        ctx.last_scene = {"location": "dapur", "activity": "masak"}
        agent = MemoraAgent(tool_ctx=ctx)
        current = agent._get_context()
        assert current is not None
        assert current.visible_people == []
        assert current.scene == "dapur"

    async def test_on_proactive_calls_generate_reply(self) -> None:
        ctx = ToolContext()
        agent = MemoraAgent(tool_ctx=ctx)
        mock_session = AsyncMock()
        mock_session.generate_reply = AsyncMock()
        type(agent).session = PropertyMock(return_value=mock_session)
        try:
            await agent._on_proactive("[PROAKTIF] beli paracetamol")
            mock_session.generate_reply.assert_awaited_once()
            instructions = mock_session.generate_reply.await_args.kwargs.get("instructions", "")
            assert "paracetamol" in instructions
        finally:
            del type(agent).session


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


class TestObservationEngineWiring:
    """Step 5: agent _get_context + _build_context_text prefer WorkingMemory."""

    def test_get_context_prefers_working_memory(self) -> None:
        from dto.observations import CurrentContext

        ctx = ToolContext()
        wm = MagicMock()
        fused = CurrentContext(
            visible_people=["Asep"], scene="apotek", speech="halo", activity="beli obat"
        )
        wm.get.return_value = fused
        ctx.working_memory = wm
        agent = MemoraAgent(tool_ctx=ctx)
        result = agent._get_context()
        assert result is fused

    def test_get_context_falls_back_when_expired(self) -> None:
        ctx = ToolContext()
        wm = MagicMock()
        wm.get.return_value = None  # expired
        ctx.working_memory = wm
        ctx.last_face = {"name": "Asep", "is_known": True, "embedding": None}
        ctx.last_scene = {"location": "apotek", "activity": "beli obat"}
        agent = MemoraAgent(tool_ctx=ctx)
        result = agent._get_context()
        assert result is not None
        assert "Asep" in result.visible_people
        assert result.scene == "apotek"

    def test_get_context_no_working_memory(self) -> None:
        ctx = ToolContext()
        ctx.last_face = {"name": "Budi", "is_known": True, "embedding": None}
        agent = MemoraAgent(tool_ctx=ctx)
        result = agent._get_context()
        assert result is not None
        assert "Budi" in result.visible_people

    async def test_build_context_text_prefers_working_memory(self) -> None:
        from dto.observations import CurrentContext

        ctx = ToolContext()
        wm = MagicMock()
        fused = CurrentContext(visible_people=["Asep"], scene="apotek", speech="siapa ini?")
        wm.get.return_value = fused
        ctx.working_memory = wm
        engine = MagicMock()
        engine.build = AsyncMock(return_value=(MagicMock(), "Orang: Asep. Lokasi: apotek."))
        agent = MemoraAgent(tool_ctx=ctx, context_engine=engine)
        text = await agent._build_context_text()
        assert "Asep" in text
        engine.build.assert_awaited_once()
        # Should pass the fused context, not a new one from last_face
        passed_ctx = engine.build.await_args.args[0]
        assert passed_ctx is fused

    async def test_build_context_text_falls_back_no_wm(self) -> None:
        ctx = ToolContext()
        ctx.last_face = {"name": "Asep", "is_known": True, "embedding": None}
        engine = MagicMock()
        engine.build = AsyncMock(return_value=(MagicMock(), "Orang: Asep."))
        agent = MemoraAgent(tool_ctx=ctx, context_engine=engine)
        text = await agent._build_context_text()
        assert "Asep" in text
