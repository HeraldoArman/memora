"""Unit tests — tool layer: all tool modules + registry + router.

Tools are thin service callers. We build a ToolContext whose services are AsyncMocks
(no DB), so every tool's validation branch + happy path is exercised.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import numpy as np
import pytest

from constants import ToolName
from dto.observations import CurrentContext, DeviceObservation, FaceObservation
from reasoning.tools.router import _resp, dispatch_tool_call
from tools import ToolContext, get_tool

# Re-import the tool modules so we test the exact callables the registry wires.
from tools.calendar import tools as cal
from tools.knowledge import tools as kn
from tools.memory import tools as mem
from tools.observation import tools as obs
from tools.person import tools as per
from tools.registry import build_registry
from tools.reminder import tools as rem
from tools.system import tools as sys_tools

SERVICES = (
    "person_service",
    "memory_service",
    "reminder_service",
    "knowledge_service",
    "event_service",
    "shopping_service",
)


def _ctx(**overrides) -> ToolContext:
    """ToolContext with all services swapped for AsyncMocks."""
    ctx = ToolContext()
    for name in SERVICES:
        setattr(ctx, name, overrides.pop(name, AsyncMock()))
    if overrides:
        raise AssertionError(f"unexpected overrides: {overrides}")
    return ctx


def _ctx_with_context(*observations) -> ToolContext:
    ctx = _ctx()
    ctx.current_context = CurrentContext(observations=list(observations))
    return ctx


def _face_ctx() -> ToolContext:
    emb = np.zeros(512, dtype=np.float32)
    return _ctx_with_context(FaceObservation(embedding=emb))


class TestObservationTools:
    async def test_current_scene_happy(self) -> None:
        ctx = _ctx()
        ctx.current_context = CurrentContext(scene="apotek", activity="beli obat", confidence=0.9)
        assert await obs.current_scene({}, ctx) == {
            "location": "apotek",
            "activity": "beli obat",
            "confidence": 0.9,
        }

    async def test_current_scene_none(self) -> None:
        assert await obs.current_scene({}, _ctx()) == {"available": False}

    async def test_visible_people(self) -> None:
        ctx = _ctx()
        ctx.current_context = CurrentContext(visible_people=["Asep"])
        assert await obs.visible_people({}, ctx) == {"available": True, "people": ["Asep"]}
        assert await obs.visible_people({}, _ctx()) == {"available": False, "people": []}

    async def test_current_activity(self) -> None:
        ctx = _ctx()
        ctx.current_context = CurrentContext(activity="makan", scene="rumah")
        assert await obs.current_activity({}, ctx) == {"activity": "makan", "location": "rumah"}

    async def test_conversation_summary(self) -> None:
        ctx = _ctx()
        ctx.memory_service.recent_memories = AsyncMock(return_value=[{"session_id": "s1"}])
        assert await obs.conversation_summary({"limit": 5}, ctx) == {
            "recent_sessions": [{"session_id": "s1"}]
        }
        ctx.memory_service.recent_memories.assert_awaited_once_with(limit=5)


class TestPersonTools:
    async def test_search_person_missing_query(self) -> None:
        assert (await per.search_person({}, _ctx()))["error"] == "query required"

    async def test_search_person_happy(self) -> None:
        ctx = _ctx()
        ctx.person_service.search_by_name = AsyncMock(return_value=[{"name": "Asep"}])
        out = await per.search_person({"query": "Asep"}, ctx)
        assert out["results"] == [{"name": "Asep"}]

    async def test_search_by_face_no_face(self) -> None:
        out = await per.search_person_by_face({}, _ctx())
        assert out["known"] is False and "no face detected" in out["note"]

    async def test_search_by_face_happy(self) -> None:
        ctx = _face_ctx()
        ctx.person_service.search_by_face = AsyncMock(
            return_value={"person_id": "p1", "known": True}
        )
        out = await per.search_person_by_face({}, ctx)
        assert out == {"person_id": "p1", "known": True}

    async def test_register_person(self) -> None:
        ctx = _ctx()
        ctx.person_service.register_person = AsyncMock(return_value={"person_id": "p1"})
        assert (await per.register_person({}, ctx))["error"] == "name required"
        assert await per.register_person({"name": "Asep"}, ctx) == {"person": {"person_id": "p1"}}

    async def test_register_face_no_person_id(self) -> None:
        assert (await per.register_face({}, _ctx()))["error"] == "person_id required"

    async def test_register_face_no_face(self) -> None:
        out = await per.register_face({"person_id": "p1"}, _ctx())
        assert out["enrolled"] is False and "no face detected" in out["note"]

    async def test_register_face_not_wired(self) -> None:
        ctx = _face_ctx()
        ctx.person_service.register_face = AsyncMock(side_effect=RuntimeError("no repo"))
        out = await per.register_face({"person_id": "p1"}, ctx)
        assert out["enrolled"] is False and "no repo" in out["note"]

    async def test_register_face_happy(self) -> None:
        ctx = _face_ctx()
        ctx.person_service.register_face = AsyncMock(return_value=3)
        assert await per.register_face({"person_id": "p1"}, ctx) == {
            "person_id": "p1",
            "enrolled": True,
            "face_index_row": 3,
        }

    async def test_update_person(self) -> None:
        ctx = _ctx()
        assert (await per.update_person({}, ctx))["error"] == "person_id required"
        ctx.person_service.update_person = AsyncMock(return_value=None)
        assert (await per.update_person({"person_id": "p9"}, ctx))["error"] == "person not found"
        ctx.person_service.update_person = AsyncMock(return_value={"person_id": "p9", "notes": "x"})
        assert await per.update_person({"person_id": "p9", "notes": "x"}, ctx) == {
            "person": {"person_id": "p9", "notes": "x"}
        }


class TestReminderTools:
    def test_parse_dt(self) -> None:
        assert rem._parse_dt(None) is None
        assert rem._parse_dt("garbage") is None
        assert rem._parse_dt("2026-08-10T09:00:00") == datetime(2026, 8, 10, 9, 0, 0)

    async def test_create_reminder(self) -> None:
        ctx = _ctx()
        assert (await rem.create_reminder({}, ctx))["error"] == "title required"
        ctx.reminder_service.create = AsyncMock(return_value={"reminder_id": "r1"})
        out = await rem.create_reminder({"title": "obat", "due_at": "2026-08-10T09:00"}, ctx)
        assert out == {"reminder_id": "r1"}
        ctx.reminder_service.create.assert_awaited_once()
        assert ctx.reminder_service.create.await_args.kwargs["due_at"] == datetime(
            2026, 8, 10, 9, 0
        )

    async def test_update_reminder(self) -> None:
        rid = str(uuid4())
        ctx = _ctx()
        assert (await rem.update_reminder({}, ctx))["error"] == "reminder_id required"
        ctx.reminder_service.update = AsyncMock(return_value=None)
        assert (await rem.update_reminder({"reminder_id": rid}, ctx))[
            "error"
        ] == "reminder not found"
        ctx.reminder_service.update = AsyncMock(
            return_value={"reminder_id": rid, "completed": True}
        )
        out = await rem.update_reminder({"reminder_id": rid, "completed": True}, ctx)
        assert out["completed"] is True

    async def test_delete_reminder(self) -> None:
        rid = str(uuid4())
        ctx = _ctx()
        assert (await rem.delete_reminder({}, ctx))["error"] == "reminder_id required"
        ctx.reminder_service.delete = AsyncMock(return_value=True)
        assert await rem.delete_reminder({"reminder_id": rid}, ctx) == {"deleted": True}

    async def test_search_reminders(self) -> None:
        ctx = _ctx()
        assert (await rem.search_reminders({}, ctx))["error"] == "query required"
        ctx.reminder_service.search = AsyncMock(return_value=[{"title": "obat"}])
        assert await rem.search_reminders({"query": "obat"}, ctx) == {
            "reminders": [{"title": "obat"}]
        }

    async def test_today_reminders(self) -> None:
        ctx = _ctx()
        ctx.reminder_service.today = AsyncMock(return_value=[])
        assert await rem.today_reminders({}, ctx) == {"reminders": []}


class TestCalendarTools:
    async def test_create_event(self) -> None:
        ctx = _ctx()
        assert (await cal.create_event({}, ctx))["error"] == "title required"
        assert (await cal.create_event({"title": "x"}, ctx))[
            "error"
        ] == "starts_at required (ISO 8601)"
        ctx.event_service.create = AsyncMock(return_value={"event_id": "e1"})
        out = await cal.create_event({"title": "kontrol", "starts_at": "2026-08-11T10:00"}, ctx)
        assert out == {"event_id": "e1"}
        ctx.event_service.create.assert_awaited_once()
        assert ctx.event_service.create.await_args.kwargs["title"] == "kontrol"

    async def test_search_schedule(self) -> None:
        ctx = _ctx()
        ctx.event_service.search = AsyncMock(return_value=[{"title": "kontrol"}])
        assert await cal.search_schedule({"query": "kontrol"}, ctx) == {
            "events": [{"title": "kontrol"}]
        }
        ctx.event_service.upcoming = AsyncMock(return_value=[])
        assert await cal.search_schedule({}, ctx) == {"events": []}

    async def test_shopping_list(self) -> None:
        ctx = _ctx()
        ctx.shopping_service.list_items = AsyncMock(return_value=[{"name": "telur"}])
        assert await cal.shopping_list({"action": "list"}, ctx) == {"items": [{"name": "telur"}]}
        assert (await cal.shopping_list({"action": "add"}, ctx))[
            "error"
        ] == "item required for add/remove/check"
        ctx.shopping_service.add = AsyncMock(return_value={"name": "telur"})
        assert await cal.shopping_list({"action": "add", "item": "telur"}, ctx) == {"name": "telur"}
        ctx.shopping_service.remove = AsyncMock(return_value=True)
        assert await cal.shopping_list({"action": "remove", "item": "telur"}, ctx) == {
            "deleted": True
        }
        ctx.shopping_service.check = AsyncMock(return_value={"name": "telur", "checked": True})
        assert await cal.shopping_list({"action": "check", "item": "telur"}, ctx) == {
            "name": "telur",
            "checked": True,
        }
        ctx.shopping_service.check = AsyncMock(return_value=None)
        assert (await cal.shopping_list({"action": "check", "item": "telur"}, ctx))[
            "error"
        ] == "item not found"
        assert (await cal.shopping_list({"action": "bogus", "item": "x"}, ctx))[
            "error"
        ] == "unknown action: bogus"


class TestKnowledgeTools:
    async def test_search_entity(self) -> None:
        ctx = _ctx()
        assert (await kn.search_entity({}, ctx))["error"] == "query required"
        ctx.knowledge_service.search_entity = AsyncMock(return_value=[{"name": "Tokopedia"}])
        assert await kn.search_entity({"query": "Toko"}, ctx) == {
            "results": [{"name": "Tokopedia"}]
        }

    async def test_entity_relationships(self) -> None:
        ctx = _ctx()
        assert (await kn.entity_relationships({}, ctx))["error"] == "entity required"
        ctx.knowledge_service.entity_relationships = AsyncMock(
            return_value={"nodes": [], "edges": []}
        )
        assert await kn.entity_relationships({"entity": "Asep"}, ctx) == {"nodes": [], "edges": []}

    async def test_search_preferences(self) -> None:
        ctx = _ctx()
        assert (await kn.search_preferences({}, ctx))["error"] == "person_id required"
        ctx.knowledge_service.preferences = AsyncMock(return_value=[{"name": "Sushi"}])
        assert await kn.search_preferences({"person_id": "p1"}, ctx) == {
            "preferences": [{"name": "Sushi"}]
        }

    async def test_related_people(self) -> None:
        ctx = _ctx()
        assert (await kn.related_people({}, ctx))["error"] == "person_id required"
        ctx.person_service.related_people = AsyncMock(return_value=[{"name": "Budi"}])
        assert await kn.related_people({"person_id": "p1"}, ctx) == {"related": [{"name": "Budi"}]}

    async def test_knowledge_graph(self) -> None:
        ctx = _ctx()
        assert (await kn.knowledge_graph({}, ctx))["error"] == "entity required"
        ctx.knowledge_service.entity_relationships = AsyncMock(return_value={"nodes": [1]})
        assert await kn.knowledge_graph({"entity": "Asep"}, ctx) == {"nodes": [1]}


class TestMemoryTools:
    async def test_search_memory(self) -> None:
        ctx = _ctx()
        assert (await mem.search_memory({}, ctx))["error"] == "query required"
        ctx.knowledge_service.search_entity = AsyncMock(return_value=[{"name": "Asep"}])
        ctx.memory_service.recent_memories = AsyncMock(return_value=[{"session_id": "s1"}])
        out = await mem.search_memory({"query": "Asep"}, ctx)
        assert out == {"entities": [{"name": "Asep"}], "episodes": [{"session_id": "s1"}]}
        ctx.memory_service.recent_memories.assert_awaited_once_with(limit=20)

    async def test_recent_memories(self) -> None:
        ctx = _ctx()
        ctx.memory_service.recent_memories = AsyncMock(return_value=[{"session_id": "s1"}])
        assert await mem.recent_memories({"limit": 3}, ctx) == {"episodes": [{"session_id": "s1"}]}
        ctx.memory_service.recent_memories.assert_awaited_once_with(limit=3)

    async def test_similar_memories_no_query(self) -> None:
        assert (await mem.similar_memories({}, _ctx()))["error"] == "query required"

    async def test_similar_memories_happy(self) -> None:
        ctx = _ctx()
        out = await mem.similar_memories({"query": "sushi"}, ctx)
        assert "results" in out  # ranker over empty candidates → [] (no DB)

    async def test_similar_memories_retrieval_failure(self) -> None:
        ctx = _ctx()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("memory.retrieval.retriever.Retriever", _BoomRetriever)
            out = await mem.similar_memories({"query": "x"}, ctx)
        assert out["results"] == [] and "retrieval failed" in out["note"]

    async def test_memory_timeline(self) -> None:
        ctx = _ctx()
        # recent_memories returns session dicts with a summary field (the only text the
        # episodic store carries); the person_id filter matches against summary content.
        ctx.memory_service.recent_memories = AsyncMock(
            return_value=[
                {"session_id": "s1", "summary": "chat about Asep"},
                {"session_id": "s2", "summary": "other topic"},
            ]
        )
        all_tl = await mem.memory_timeline({}, ctx)
        assert len(all_tl["timeline"]) == 2
        filtered = await mem.memory_timeline({"person_id": "Asep"}, ctx)
        assert len(filtered["timeline"]) == 1 and "Asep" in filtered["timeline"][0]["summary"]


class _BoomRetriever:
    async def retrieve(self, *a, **k):
        raise RuntimeError("db down")


class TestSystemTools:
    def _dev_ctx(self) -> ToolContext:
        return _ctx_with_context(DeviceObservation(battery_level=80, wifi_connected=True))

    async def test_battery_status(self) -> None:
        assert await sys_tools.battery_status({}, _ctx()) == {"available": False}
        assert await sys_tools.battery_status({}, self._dev_ctx()) == {
            "battery_level": 80,
            "available": True,
        }

    async def test_network_status(self) -> None:
        assert await sys_tools.network_status({}, _ctx()) == {"available": False}
        assert await sys_tools.network_status({}, self._dev_ctx()) == {
            "wifi_connected": True,
            "available": True,
        }

    async def test_device_information(self) -> None:
        out = await sys_tools.device_information({}, self._dev_ctx())
        assert out["device"]["battery_level"] == 80
        assert "firmware" in out

    async def test_firmware_version(self) -> None:
        out = await sys_tools.firmware_version({}, _ctx())
        assert "0.1.0" in out["firmware_version"]


class TestToolContext:
    def test_services_wired(self) -> None:
        ctx = ToolContext()
        for name in SERVICES:
            assert getattr(ctx, name) is not None

    def test_post_init_rebuilds_person_service_with_face_repo(self) -> None:
        fake_repo = object()
        ctx = ToolContext(face_repo=fake_repo)
        assert ctx.person_service.face_repo is fake_repo

    def test_current_face_embedding(self) -> None:
        assert _ctx().current_face_embedding() is None
        emb = np.ones(512, dtype=np.float32)
        ctx = _ctx_with_context(FaceObservation(embedding=emb))
        assert ctx.current_face_embedding() is emb

    def test_device_snapshot(self) -> None:
        assert _ctx().device_snapshot() == {}
        ctx = _ctx_with_context(DeviceObservation(battery_level=55, wifi_connected=False))
        snap = ctx.device_snapshot()
        assert snap == {"battery_level": 55, "wifi_connected": False, "button_pressed": False}


class TestRegistry:
    def test_registry_equals_declared_surface(self) -> None:
        from schemas import ALL_FUNCTION_DECLARATIONS

        reg = build_registry()
        declared = {d["name"] for d in ALL_FUNCTION_DECLARATIONS}
        assert set(reg) == declared
        assert len(reg) == len(ToolName)

    def test_get_tool(self) -> None:
        assert get_tool("firmware_version") is sys_tools.firmware_version
        assert get_tool("nope") is None


class TestRouter:
    def test_resp_shape(self) -> None:
        assert _resp("c1", "x", {"a": 1}) == {"id": "c1", "name": "x", "response": {"a": 1}}

    async def test_dispatch_known_and_unknown(self) -> None:
        from google.genai import types

        from tools import registry as reg

        async def _fake(args, ctx):
            return {"ok": True}

        orig = reg.build_registry()
        reg._REGISTRY = {**orig, "firmware_version": _fake}
        try:
            tc = types.LiveServerToolCall(
                function_calls=[
                    types.FunctionCall(id="c1", name="firmware_version", args={}),
                    types.FunctionCall(id="c2", name="bogus", args={}),
                ]
            )
            resps = await dispatch_tool_call(tc, _ctx())
        finally:
            reg._REGISTRY = orig
        assert resps[0]["id"] == "c1" and resps[0]["response"] == {"ok": True}
        assert "unknown tool" in resps[1]["response"]["error"]

    async def test_dispatch_tool_error_is_caught(self) -> None:
        from google.genai import types

        from tools import registry as reg

        async def _boom(args, ctx):
            raise ValueError("kaboom")

        orig = reg.build_registry()
        reg._REGISTRY = {**orig, "firmware_version": _boom}
        try:
            tc = types.LiveServerToolCall(
                function_calls=[types.FunctionCall(id="c1", name="firmware_version", args={})]
            )
            resps = await dispatch_tool_call(tc, _ctx())
        finally:
            reg._REGISTRY = orig
        assert "ValueError" in resps[0]["response"]["error"]

    async def test_dispatch_empty_calls(self) -> None:
        from google.genai import types

        resps = await dispatch_tool_call(types.LiveServerToolCall(function_calls=[]), _ctx())
        assert resps == []
