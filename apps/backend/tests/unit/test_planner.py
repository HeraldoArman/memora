"""Unit tests — proactive planner: context-vs-reminder matching + cooldown.

No DB: reminder + shopping services are AsyncMocks. Verifies keyword overlap detection,
cooldown dedup, and the periodic run loop.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import numpy as np

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


class TestUnknownPersonTrigger:
    """Programmatic 'Siapa ini?' trigger: fires when an unknown person is visible
    and the user is talking. Prevents orphan facts in 24/7 glasses sessions."""

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

    async def test_unknown_person_with_speech_fires(self) -> None:
        planner, _ = self._planner()
        ctx = CurrentContext(
            visible_people=["Orang tidak dikenali"], speech="apa makanan favoritmu?"
        )
        result = await planner.check(ctx)
        assert result is not None
        assert "Siapa ini" in result
        assert "[PROAKTIF]" in result

    async def test_unknown_person_without_speech_no_fire(self) -> None:
        planner, _ = self._planner()
        ctx = CurrentContext(visible_people=["Orang tidak dikenali"], speech=None)
        assert await planner.check(ctx) is None

    async def test_unknown_person_empty_speech_no_fire(self) -> None:
        planner, _ = self._planner()
        ctx = CurrentContext(visible_people=["Orang tidak dikenali"], speech="  ")
        assert await planner.check(ctx) is None

    async def test_known_person_no_fire(self) -> None:
        planner, _ = self._planner()
        ctx = CurrentContext(visible_people=["Asep"], speech="halo")
        result = await planner.check(ctx)
        assert result is None or "Siapa ini" not in result

    async def test_possible_match_no_fire(self) -> None:
        """Possible match ('Mungkin <name>') should NOT trigger 'Siapa ini?' —
        the agent asks 'Is this <name>?' via the system prompt instead."""
        planner, _ = self._planner()
        ctx = CurrentContext(visible_people=["Mungkin Budi"], speech="halo")
        result = await planner.check(ctx)
        assert result is None or "Siapa ini" not in result

    async def test_unknown_person_cooldown(self) -> None:
        planner, C = self._planner()
        ctx = CurrentContext(visible_people=["Orang tidak dikenali"], speech="halo")
        # First fire
        assert await planner.check(ctx) is not None
        # Within 2 min → blocked
        C.t = 60.0
        assert await planner.check(ctx) is None
        # After 2 min → fires again
        C.t = 130.0
        result = await planner.check(ctx)
        assert result is not None and "Siapa ini" in result

    async def test_unknown_person_does_not_block_reminder_check(self) -> None:
        """Unknown person trigger fires first, but reminder check should still work
        on the next check() call (different cooldown keys)."""
        planner, C = self._planner(cooldown_s=100)
        # Fire unknown person trigger
        ctx_unknown = CurrentContext(visible_people=["Orang tidak dikenali"], speech="halo")
        assert await planner.check(ctx_unknown) is not None
        # Now a scene with a matching reminder should still fire (different key)
        C.t = 1.0
        planner.reminder_service.upcoming = AsyncMock(
            return_value=[{"reminder_id": "r1", "title": "paracetamol", "completed": False}]
        )
        ctx_reminder = CurrentContext(scene="paracetamol", visible_people=["Asep"])
        result = await planner.check(ctx_reminder)
        assert result is not None and "paracetamol" in result


class TestSemanticMatching:
    """Do Soon #4: embedding similarity for location→item matching."""

    class _FakeEmbedder:
        async def embed_batch(self, texts):
            vecs = {
                "apotek": np.array([0.9, 0.1, 0.0], dtype=np.float32),
                "beli paracetamol": np.array([0.85, 0.15, 0.0], dtype=np.float32),
                "telur": np.array([0.0, 0.0, 1.0], dtype=np.float32),
                "restoran": np.array([0.0, 0.9, 0.1], dtype=np.float32),
                "makan siang": np.array([0.1, 0.85, 0.05], dtype=np.float32),
            }
            return [vecs.get(t, np.zeros(3, dtype=np.float32)) for t in texts]

    def _planner_with_embedder(self, *, cooldown_s=100, clock=None):
        class C:
            t = 0.0

        planner = ProactivePlanner(
            reminder_service=AsyncMock(),
            shopping_service=AsyncMock(),
            cooldown_s=cooldown_s,
            text_embedder=self._FakeEmbedder(),
            _clock=clock or (lambda: C.t),
        )
        planner.reminder_service.upcoming = AsyncMock(return_value=[])
        planner.shopping_service.list_items = AsyncMock(return_value=[])
        return planner, C

    async def test_semantic_match_no_keyword_overlap(self) -> None:
        """apotek vs beli paracetamol — no keyword overlap, semantic match fires."""
        planner, _ = self._planner_with_embedder()
        planner.reminder_service.upcoming = AsyncMock(
            return_value=[{"reminder_id": "r1", "title": "beli paracetamol", "completed": False}]
        )
        ctx = CurrentContext(scene="apotek")
        result = await planner.check(ctx)
        assert result is not None and "paracetamol" in result, result

    async def test_semantic_no_match(self) -> None:
        """apotek vs telur — both keyword and semantic miss."""
        planner, _ = self._planner_with_embedder()
        planner.shopping_service.list_items = AsyncMock(
            return_value=[{"name": "telur", "checked": False}]
        )
        ctx = CurrentContext(scene="apotek")
        result = await planner.check(ctx)
        assert result is None, f"expected None: {result}"

    async def test_keyword_takes_priority_over_semantic(self) -> None:
        """When keyword matches, semantic pass is skipped."""
        planner, C = self._planner_with_embedder(cooldown_s=100)
        planner.reminder_service.upcoming = AsyncMock(
            return_value=[
                {"reminder_id": "r1", "title": "paracetamol", "completed": False},
            ]
        )
        ctx = CurrentContext(scene="paracetamol")
        result = await planner.check(ctx)
        assert result is not None and "paracetamol" in result

    async def test_no_embedder_keyword_only(self) -> None:
        """Without text_embedder, only keyword matching works (backward compat)."""
        planner, C = self._planner_with_embedder()
        planner.text_embedder = None
        planner.reminder_service.upcoming = AsyncMock(
            return_value=[{"reminder_id": "r1", "title": "beli paracetamol", "completed": False}]
        )
        ctx = CurrentContext(scene="apotek")
        assert await planner.check(ctx) is None

    async def test_embedder_failure_falls_back(self) -> None:
        """If embed_batch raises, semantic pass silently fails, keyword result stands."""
        planner, _ = self._planner_with_embedder()

        class _BoomEmbedder:
            async def embed_batch(self, texts):
                raise RuntimeError("API down")

        planner.text_embedder = _BoomEmbedder()
        planner.reminder_service.upcoming = AsyncMock(
            return_value=[{"reminder_id": "r1", "title": "paracetamol", "completed": False}]
        )
        ctx = CurrentContext(scene="paracetamol")
        result = await planner.check(ctx)
        assert result is not None and "paracetamol" in result
