"""Unit tests — context: packager, summarizer, context engine.

Packager/summarizer are pure (client stubbed). ContextEngine.build degrades on store
failure and still folds in reminders + the current snapshot.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from context.engine import ContextEngine
from context.packager import package, to_text
from context.summarizer import Summarizer
from dto.memory import ContextPackage
from dto.observations import CurrentContext
from memory.ranking.ranker import rank


class TestPackager:
    def _ranked(self):
        return rank(
            [
                {
                    "content": "Asep works at Tokopedia",
                    "category": "Person",
                    "source": "neo4j",
                    "source_id": "pid1",
                    "created_at": "2026-08-09T12:00:00+00:00",
                },
                {
                    "content": "met Asep",
                    "category": "Episodic",
                    "source": "postgres",
                    "source_id": "s1",
                    "created_at": "2026-08-08T12:00:00+00:00",
                },
            ],
            query="Asep",
            visible_people=["Asep"],
        )

    def test_package_shape(self) -> None:
        ranked = self._ranked()
        ctx = CurrentContext(visible_people=["Asep"], scene="apotek", device="baterai 72%")
        pkg = package(
            ranked=ranked,
            current=ctx,
            reminders=["beli obat 15:00"],
            user_question="Siapa ini?",
            conversation_history=["halo", "apa kabar"],
        )
        assert isinstance(pkg, ContextPackage)
        assert len(pkg.relevant_facts) == 2
        assert pkg.visible_people == ["Asep"]
        assert pkg.location == "apotek"
        assert pkg.device_context == "baterai 72%"
        assert pkg.user_question == "Siapa ini?"
        assert pkg.upcoming_reminders == ["beli obat 15:00"]
        assert pkg.conversation_history == ["halo", "apa kabar"]
        assert pkg.provenance  # provenance keyed by fact_id

    def test_package_category_fallback(self) -> None:
        from constants import MemoryCategory

        ranked = self._ranked()
        pkg = package(ranked=ranked)
        # Person label → PERSON; Episodic (not a MemoryCategory) → OBJECT fallback
        cats = {f.category for f in pkg.relevant_facts}
        assert MemoryCategory.PERSON in cats and MemoryCategory.OBJECT in cats

    def test_package_top_k_and_empty_content_skipped(self) -> None:
        ranked = self._ranked() + [({"content": "", "source": "x"}, 0.1, {})]
        pkg = package(ranked=ranked, top_k=1)
        assert len(pkg.relevant_facts) == 1  # top_k=1, empty-content candidate dropped

    def test_package_no_current(self) -> None:
        pkg = package(ranked=[])
        assert pkg.location is None and pkg.visible_people == []

    def test_to_text_empty(self) -> None:
        assert to_text(package(ranked=[])) == "(belum ada konteks)"

    def test_to_text_sections(self) -> None:
        ranked = self._ranked()
        pkg = package(
            ranked=ranked,
            current=CurrentContext(visible_people=["Asep"], scene="apotek"),
            reminders=["obat"],
            user_question="siapa ini",
        )
        txt = to_text(pkg, activity="beli obat")
        assert "Lokasi: apotek" in txt
        assert "Orang terlihat: Asep" in txt
        assert "Aktivitas: beli obat" in txt
        assert "Fakta diketahui:" in txt
        assert "Pengingat: obat" in txt
        assert "Pertanyaan: siapa ini" in txt


class TestSummarizer:
    def test_needs_summary(self) -> None:
        s = Summarizer(client=object(), char_budget=100)
        assert not s.needs_summary("short")
        assert s.needs_summary("x" * 200)

    async def test_under_budget_returns_original_no_api(self) -> None:
        s = Summarizer(char_budget=100)
        out = await s.summarize("short text")
        assert out == "short text"

    async def test_api_failure_truncates(self) -> None:
        bad = MagicMock()
        bad.models.generate_content = MagicMock(side_effect=RuntimeError("no key"))
        s = Summarizer(char_budget=10)
        s._client = bad
        out = await s.summarize("a very long text that exceeds the budget")
        assert out == "a very long text that exceeds the budget"[:10]

    async def test_api_success_returns_summary(self) -> None:
        client = MagicMock()
        resp = type("R", (), {"text": "ringkasan", "parsed": None})
        client.models.generate_content = MagicMock(return_value=resp)
        s = Summarizer(char_budget=10)
        s._client = client
        out = await s.summarize("x" * 100)
        assert out == "ringkasan"


class TestContextEngine:
    def _engine(self) -> ContextEngine:
        engine = ContextEngine(
            retriever=AsyncMock(),
            summarizer=AsyncMock(),
            reminder_service=AsyncMock(),
        )
        engine.reminder_service.upcoming = AsyncMock(
            return_value=[
                {"title": "minum obat", "due_at": "2026-08-10T09:00:00+00:00", "completed": False},
                {"title": "kontrol", "due_at": None, "completed": True},  # completed → dropped
            ]
        )
        return engine

    async def test_build_happy_path(self) -> None:
        engine = self._engine()
        engine.retriever.retrieve = AsyncMock(
            return_value=[{"content": "Asep works at Tokopedia", "category": "Person"}]
        )
        engine.summarizer.summarize = AsyncMock(return_value="summarized")
        ctx = CurrentContext(visible_people=["Asep"], scene="apotek", speech="Siapa ini?")
        pkg, text = await engine.build(ctx, user_question="Siapa ini?")
        assert text == "summarized"
        assert pkg.visible_people == ["Asep"]
        # completed reminder filtered out
        assert pkg.upcoming_reminders == ["minum obat (2026-08-10T09:00:00+00:00)"]
        engine.retriever.retrieve.assert_awaited_once_with("Siapa ini?", visible_people=["Asep"])

    async def test_build_retrieval_failure_degrades(self) -> None:
        engine = self._engine()
        engine.retriever.retrieve = AsyncMock(side_effect=RuntimeError("neo4j down"))
        engine.summarizer.summarize = AsyncMock(side_effect=RuntimeError("gemini down"))
        ctx = CurrentContext(visible_people=["Asep"], scene="apotek")
        pkg, text = await engine.build(ctx, user_question="Siapa ini?")
        assert pkg is not None
        assert "Asep" in text and "minum obat" in text  # snapshot + reminders still folded

    async def test_build_no_current(self) -> None:
        engine = self._engine()
        engine.retriever.retrieve = AsyncMock(return_value=[])
        engine.summarizer.summarize = AsyncMock(side_effect=lambda t: t)
        pkg, text = await engine.build(None)
        assert pkg.location is None and pkg.visible_people == []
        # no query/speech → empty query passed through
        engine.retriever.retrieve.assert_awaited_once_with("", visible_people=[])
