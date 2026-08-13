"""Proactive planner — detect context changes and trigger proactive reminders.

proposal.md §3 (Proactive Everyday Assistance): if the user enters a pharmacy after
previously planning to buy paracetamol, the system proactively reminds them.

The planner runs on a periodic loop (default 30s), checks the current scene against
pending reminders + shopping list items, and if a match is found, injects a text
instruction into the Gemini Live session via send_text(). The model then generates
the spoken reminder.

The "Siapa ini?" unknown-person trigger was removed: it fired on a 30s/2min timer
and interrupted the user mid-conversation. Face registration is now user-driven —
the system prompt asks "Siapa ini?" only when the user engages with an unknown
person, not on a timer.

Cooldown: each (reminder_id, location) pair only fires once per cooldown window
(default 5 min) so we don't nag.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

import numpy as np

from dto.observations import CurrentContext

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL_S = 30.0
_DEFAULT_COOLDOWN_S = 300.0
_SEMANTIC_THRESHOLD = 0.5  # cosine similarity for location→item matching


class ProactivePlanner:
    """Periodically check context vs reminders/shopping → trigger proactive prompts."""

    def __init__(
        self,
        *,
        reminder_service,
        shopping_service,
        interval_s: float = _DEFAULT_INTERVAL_S,
        cooldown_s: float = _DEFAULT_COOLDOWN_S,
        text_embedder=None,
        _clock=time.monotonic,
    ) -> None:
        self.reminder_service = reminder_service
        self.shopping_service = shopping_service
        self.interval_s = interval_s
        self.cooldown_s = cooldown_s
        self.text_embedder = text_embedder
        self._clock = _clock
        self._fired: dict[tuple[str, str], float] = {}  # (item_id, location) → last_fired
        self._task: asyncio.Task | None = None

    async def check(self, current: CurrentContext | None) -> str | None:
        """Return a proactive prompt string if a match is found, else None."""
        if current is None:
            return None

        if not current.scene:
            return None
        location = current.scene.lower()

        # Gather candidates: (id, text, label, kind)
        candidates: list[tuple[str, str, str, str]] = []
        try:
            reminders = await self.reminder_service.upcoming(limit=20)
        except Exception:  # noqa: BLE001
            log.warning("planner: reminder fetch failed")
            reminders = []
        for r in reminders:
            if r.get("completed"):
                continue
            title = (r.get("title") or "").lower()
            note = (r.get("note") or "").lower()
            text = f"{title} {note}".strip()
            rid = str(r.get("reminder_id", title))
            candidates.append((rid, text, r.get("title", ""), "reminder"))

        try:
            items = await self.shopping_service.list_items()
        except Exception:  # noqa: BLE001
            log.warning("planner: shopping fetch failed")
            items = []
        for item in items:
            if item.get("checked"):
                continue
            name = (item.get("name") or "").lower()
            iid = str(item.get("name", name))
            candidates.append((iid, name, item.get("name", ""), "shopping"))

        # Pass 1: keyword overlap (free)
        unmatched: list[tuple[str, str, str, str]] = []
        for cid, text, label, kind in candidates:
            if _keyword_overlap(location, text):
                if self._should_fire(cid, location):
                    self._mark_fired(cid, location)
                    return _build_prompt_for(kind, label, current.scene)
                continue
            unmatched.append((cid, text, label, kind))

        # Pass 2: semantic similarity (one batch embed call per cycle)
        if self.text_embedder is not None and unmatched:
            match = await self._semantic_match(location, unmatched)
            if match is not None:
                cid, _text, label, kind = match
                if self._should_fire(cid, location):
                    self._mark_fired(cid, location)
                    return _build_prompt_for(kind, label, current.scene)

        return None

    async def _semantic_match(
        self, location: str, unmatched: list[tuple[str, str, str, str]]
    ) -> tuple[str, str, str, str] | None:
        """Embed location + unmatched texts, return best match above threshold."""
        try:
            texts = [location] + [text for _, text, _, _ in unmatched]
            embeddings = await self.text_embedder.embed_batch(texts)
            if not embeddings or embeddings[0] is None:
                return None
            loc_vec = embeddings[0]
            best_score = _SEMANTIC_THRESHOLD
            best: tuple[str, str, str, str] | None = None
            for i, emb in enumerate(embeddings[1:]):
                if emb is None:
                    continue
                score = float(np.dot(loc_vec, emb))
                if score > best_score:
                    best_score = score
                    best = unmatched[i]
            return best
        except Exception:  # noqa: BLE001
            log.warning("planner: semantic match failed", exc_info=True)
            return None

    def start(
        self,
        get_context: Callable[[], CurrentContext | None],
        on_trigger: Callable[[str], Awaitable[None]],
    ) -> None:
        """Start the periodic check loop."""
        self._task = asyncio.create_task(
            self._run(get_context, on_trigger), name="proactive-planner"
        )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self, get_context, on_trigger) -> None:
        while True:
            try:
                ctx = get_context()
                prompt = await self.check(ctx)
                if prompt:
                    await on_trigger(prompt)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("planner loop error")
            await asyncio.sleep(self.interval_s)

    def _should_fire(self, item_id: str, location: str, *, cooldown: float | None = None) -> bool:
        key = (item_id, location)
        last = self._fired.get(key)
        if last is None:
            return True
        cd = cooldown if cooldown is not None else self.cooldown_s
        return (self._clock() - last) >= cd

    def _mark_fired(self, item_id: str, location: str) -> None:
        self._fired[(item_id, location)] = self._clock()


def _keyword_overlap(location: str, text: str) -> bool:
    """True if any location keyword appears in the text (or vice versa)."""
    loc_words = {w for w in location.split() if len(w) > 2}
    text_words = {w for w in text.split() if len(w) > 2}
    if not loc_words or not text_words:
        return False
    return bool(loc_words & text_words) or any(
        lw in text or tw in location for lw in loc_words for tw in text_words
    )


def _build_prompt(text: str) -> str:
    return f"[PROAKTIF] {text}"


def _build_prompt_for(kind: str, label: str, scene: str | None) -> str:
    if kind == "reminder":
        return _build_prompt(
            f"Pengguna berada di {scene}. Ada pengingat: {label}. "
            f"Beritahu pengguna secara singkat dan hangat."
        )
    return _build_prompt(
        f"Pengguna berada di {scene}. Ada item belanja: {label}. "
        f"Beritahu pengguna secara singkat dan hangat."
    )


# --- self-check ---
def _self_check() -> None:  # pragma: no cover
    import asyncio
    from unittest.mock import AsyncMock

    from dto.observations import CurrentContext

    class C:
        t = 0.0

    planner = ProactivePlanner(
        reminder_service=AsyncMock(),
        shopping_service=AsyncMock(),
        cooldown_s=100,
        _clock=lambda: C.t,
    )
    planner.reminder_service.upcoming = AsyncMock(
        return_value=[{"reminder_id": "r1", "title": "beli paracetamol", "completed": False}]
    )
    planner.shopping_service.list_items = AsyncMock(
        return_value=[{"name": "telur", "checked": False}]
    )

    async def _run() -> None:
        # apotek matches "beli paracetamol" (overlap: "beli")
        # ponytail: keyword overlap is loose; "apotek" doesn't overlap "paracetamol" directly.
        # The real match here is via the reminder title containing "beli" — let's test with a
        # location that shares a word with the title.
        ctx = CurrentContext(scene="apotek")
        result = await planner.check(ctx)
        # "apotek" vs "beli paracetamol" — no word overlap. So this should be None.
        assert result is None, f"expected None for no overlap: {result}"

        # Now test with a location that shares a word
        ctx2 = CurrentContext(scene="paracetamol")
        result2 = await planner.check(ctx2)
        assert result2 is not None and "paracetamol" in result2, result2

        # Cooldown: second check within window → None
        C.t = 10.0
        result3 = await planner.check(ctx2)
        assert result3 is None, f"expected None during cooldown: {result3}"

        # After cooldown → fires again
        C.t = 200.0
        result4 = await planner.check(ctx2)
        assert result4 is not None, "expected fire after cooldown"

        # --- Semantic matching (text_embedder wired) ---
        # "apotek" vs "beli paracetamol" — no keyword overlap, but semantically close
        class _FakeEmbedder:
            async def embed_batch(self, texts):
                # Return deterministic vectors: location "apotek" is close to
                # "beli paracetamol" but far from "telur"
                vecs = {
                    "apotek": np.array([0.9, 0.1, 0.0], dtype=np.float32),
                    "beli paracetamol": np.array([0.85, 0.15, 0.0], dtype=np.float32),
                    "telur": np.array([0.0, 0.0, 1.0], dtype=np.float32),
                }
                return [vecs.get(t, np.zeros(3, dtype=np.float32)) for t in texts]

        planner2 = ProactivePlanner(
            reminder_service=AsyncMock(),
            shopping_service=AsyncMock(),
            cooldown_s=100,
            text_embedder=_FakeEmbedder(),
            _clock=lambda: C.t,
        )
        planner2.reminder_service.upcoming = AsyncMock(
            return_value=[{"reminder_id": "r1", "title": "beli paracetamol", "completed": False}]
        )
        planner2.shopping_service.list_items = AsyncMock(
            return_value=[{"name": "telur", "checked": False}]
        )
        ctx_sem = CurrentContext(scene="apotek")
        result_sem = await planner2.check(ctx_sem)
        assert result_sem is not None and "paracetamol" in result_sem, result_sem

    asyncio.run(_run())
    print("planner self-check OK: keyword + semantic match, cooldown")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
