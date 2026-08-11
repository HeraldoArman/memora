"""Unit tests — proactive planner: context-vs-reminder matching + cooldown.

No DB: reminder + shopping services are AsyncMocks. Verifies keyword overlap detection,
cooldown dedup, and the periodic run loop.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from dto.observations import CurrentContext
from reasoning.planner.planner import ProactivePlanner, _keyword_overlap


class TestKeywordOverlap:
    def test_shared_word(self) -> None:
        assert _keyword_overlap("apotek", "beli obat di apotek") is True

    def test_no_overlap(self) -> None:
        assert _keyword_overlap("apotek", "paracetamol") is False

    def test_empty(self) -> None:
        assert _keyword_overlap("", "paracetamol") is False
        assert _keyword_overlap("apotek", "") is False

    def test_short_words_ignored(self) -> None:
        # words <= 2 chars are filtered
        assert _keyword_overlap("di", "di") is False


class TestProactivePlanner:
    def _planner(self, *, cooldown_s=100, clock=None):
        class C:
            t = 0.0

        planner = ProactivePlanner(
            reminder_service=AsyncMock(),
            shopping_service=AsyncMock(),
            cooldown_s=cooldown_s,
            _clock=clock or (lambda: C.t),
        )
        planner.reminder_service.upcoming = AsyncMock(return_value=[])
        planner.shopping_service.list_items = AsyncMock(return_value=[])
        return planner, C

    async def test_no_context(self) -> None:
        planner, _ = self._planner()
        assert await planner.check(None) is None

    async def test_no_scene(self) -> None:
        planner, _ = self._planner()
        ctx = CurrentContext(scene=None)
        assert await planner.check(ctx) is None

    async def test_reminder_match(self) -> None:
        planner, C = self._planner()
        planner.reminder_service.upcoming = AsyncMock(
            return_value=[{"reminder_id": "r1", "title": "beli paracetamol", "completed": False}]
        )
        ctx = CurrentContext(scene="paracetamol")
        result = await planner.check(ctx)
        assert result is not None
        assert "paracetamol" in result
        assert "[PROAKTIF]" in result

    async def test_completed_reminder_skipped(self) -> None:
        planner, _ = self._planner()
        planner.reminder_service.upcoming = AsyncMock(
            return_value=[{"reminder_id": "r1", "title": "paracetamol", "completed": True}]
        )
        ctx = CurrentContext(scene="paracetamol")
        assert await planner.check(ctx) is None

    async def test_shopping_match(self) -> None:
        planner, _ = self._planner()
        planner.shopping_service.list_items = AsyncMock(
            return_value=[{"name": "paracetamol", "checked": False}]
        )
        ctx = CurrentContext(scene="paracetamol")
        result = await planner.check(ctx)
        assert result is not None
        assert "paracetamol" in result

    async def test_checked_item_skipped(self) -> None:
        planner, _ = self._planner()
        planner.shopping_service.list_items = AsyncMock(
            return_value=[{"name": "paracetamol", "checked": True}]
        )
        ctx = CurrentContext(scene="paracetamol")
        assert await planner.check(ctx) is None

    async def test_cooldown_blocks_refire(self) -> None:
        planner, C = self._planner(cooldown_s=100)
        planner.reminder_service.upcoming = AsyncMock(
            return_value=[{"reminder_id": "r1", "title": "paracetamol", "completed": False}]
        )
        ctx = CurrentContext(scene="paracetamol")
        # first fire
        assert await planner.check(ctx) is not None
        # second within cooldown → blocked
        C.t = 10.0
        assert await planner.check(ctx) is None
        # after cooldown → fires again
        C.t = 200.0
        assert await planner.check(ctx) is not None

    async def test_no_match(self) -> None:
        planner, _ = self._planner()
        planner.reminder_service.upcoming = AsyncMock(
            return_value=[{"reminder_id": "r1", "title": "beli obat", "completed": False}]
        )
        ctx = CurrentContext(scene="restoran")
        assert await planner.check(ctx) is None

    async def test_run_loop_triggers_on_match(self) -> None:
        planner, C = self._planner(cooldown_s=1000)
        planner.reminder_service.upcoming = AsyncMock(
            return_value=[{"reminder_id": "r1", "title": "paracetamol", "completed": False}]
        )
        triggered: list[str] = []

        async def on_trigger(text: str) -> None:
            triggered.append(text)

        planner.start(lambda: CurrentContext(scene="paracetamol"), on_trigger)
        await asyncio.sleep(0.5)
        await planner.stop()
        assert len(triggered) >= 1, f"expected at least 1 trigger, got {triggered}"
        assert "paracetamol" in triggered[0]

    async def test_run_loop_no_trigger_on_no_match(self) -> None:
        planner, _ = self._planner()
        triggered: list[str] = []

        async def on_trigger(text: str) -> None:
            triggered.append(text)

        planner.interval_s = 0.1
        planner.start(lambda: CurrentContext(scene="restoran"), on_trigger)
        await asyncio.sleep(0.3)
        await planner.stop()
        assert triggered == []
