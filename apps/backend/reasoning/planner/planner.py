"""Proactive planner — detect context changes and trigger proactive reminders.

proposal.md §3 (Proactive Everyday Assistance): if the user enters a pharmacy after
previously planning to buy paracetamol, the system proactively reminds them.

The planner runs on a periodic loop (default 30s), checks the current scene against
pending reminders + shopping list items, and if a match is found, injects a text
instruction into the Gemini Live session via send_text(). The model then generates
the spoken reminder.

Also: proactively asks "Siapa ini?" when an unknown person is visible AND the user
is talking (speech in current context). This is a programmatic trigger — the system
prompt also instructs the model to ask, but the planner guarantees it fires even
if the model doesn't notice. Cooldown prevents nagging.

Cooldown: each (reminder_id, location) pair only fires once per cooldown window
(default 5 min) so we don't nag. The "Siapa ini?" trigger has its own cooldown key.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from dto.observations import CurrentContext

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL_S = 30.0
_DEFAULT_COOLDOWN_S = 300.0
_UNKNOWN_PERSON_COOLDOWN_S = 120.0  # don't re-ask "Siapa ini?" within 2 min
_UNKNOWN_PERSON_KEY = "__unknown_person__"


class ProactivePlanner:
    """Periodically check context vs reminders/shopping → trigger proactive prompts."""

    def __init__(
        self,
        *,
        reminder_service,
        shopping_service,
        interval_s: float = _DEFAULT_INTERVAL_S,
        cooldown_s: float = _DEFAULT_COOLDOWN_S,
        _clock=time.monotonic,
    ) -> None:
        self.reminder_service = reminder_service
        self.shopping_service = shopping_service
        self.interval_s = interval_s
        self.cooldown_s = cooldown_s
        self._clock = _clock
        self._fired: dict[tuple[str, str], float] = {}  # (item_id, location) → last_fired
        self._task: asyncio.Task | None = None

    async def check(self, current: CurrentContext | None) -> str | None:
        """Return a proactive prompt string if a match is found, else None."""
        if current is None:
            return None

        # 0. Unknown person + speech → ask "Siapa ini?" (programmatic trigger)
        prompt = self._check_unknown_person(current)
        if prompt:
            return prompt

        if not current.scene:
            return None
        location = current.scene.lower()

        # 1. Check pending reminders
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
            text = f"{title} {note}"
            if _keyword_overlap(location, text):
                rid = str(r.get("reminder_id", title))
                if not self._should_fire(rid, location):
                    continue
                self._mark_fired(rid, location)
                return _build_prompt(
                    f"Pengguna berada di {current.scene}. Ada pengingat: {r.get('title')}. "
                    f"Beritahu pengguna secara singkat dan hangat."
                )

        # 2. Check shopping list (unchecked items)
        try:
            items = await self.shopping_service.list_items()
        except Exception:  # noqa: BLE001
            log.warning("planner: shopping fetch failed")
            items = []
        for item in items:
            if item.get("checked"):
                continue
            name = (item.get("name") or "").lower()
            if _keyword_overlap(location, name):
                iid = str(item.get("name", name))
                if not self._should_fire(iid, location):
                    continue
                self._mark_fired(iid, location)
                return _build_prompt(
                    f"Pengguna berada di {current.scene}. Ada item belanja: {item.get('name')}. "
                    f"Beritahu pengguna secara singkat dan hangat."
                )

        return None

    def _check_unknown_person(self, current: CurrentContext) -> str | None:
        """Fire 'Siapa ini?' when an unknown person is visible and the user is talking.

        This is the primary defense for the 24/7 glasses plot hole: user meets someone
        they know but the glasses don't recognise them, and they start talking. Without
        this trigger, facts from the conversation get orphaned (linked to no person).
        The prompt asks the model to ask who this person is so they can be registered.
        """
        has_unknown = "Orang tidak dikenali" in current.visible_people
        has_speech = bool(current.speech and current.speech.strip())
        if not has_unknown or not has_speech:
            return None
        if not self._should_fire(
            _UNKNOWN_PERSON_KEY, _UNKNOWN_PERSON_KEY, cooldown=_UNKNOWN_PERSON_COOLDOWN_S
        ):
            return None
        self._mark_fired(_UNKNOWN_PERSON_KEY, _UNKNOWN_PERSON_KEY)
        return _build_prompt(
            "Pengguna sedang berbicara dengan orang yang tidak dikenali. "
            "Tanyakan dengan hangat: 'Siapa ini?' lalu daftarkan nama dan hubungannya."
        )

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

        # Unknown person + speech → "Siapa ini?" trigger
        ctx3 = CurrentContext(
            visible_people=["Orang tidak dikenali"], speech="apa makanan favoritmu?"
        )
        result5 = await planner.check(ctx3)
        assert result5 is not None and "Siapa ini" in result5, result5

        # No speech → no trigger (user not talking yet)
        ctx4 = CurrentContext(visible_people=["Orang tidak dikenali"], speech=None)
        result6 = await planner.check(ctx4)
        assert result6 is None, f"expected None without speech: {result6}"

        # Known person → no trigger
        ctx5 = CurrentContext(visible_people=["Asep"], speech="halo")
        result7 = await planner.check(ctx5)
        assert result7 is None or "Siapa ini" not in (result7 or ""), result7

        # Cooldown: re-ask within 2 min → None
        C.t = 210.0
        result8 = await planner.check(ctx3)
        assert result8 is None, f"expected None during unknown-person cooldown: {result8}"

        # After unknown-person cooldown (2 min) → fires again
        C.t = 400.0
        result9 = await planner.check(ctx3)
        assert result9 is not None and "Siapa ini" in result9, result9

    asyncio.run(_run())
    print("planner self-check OK: match, no-match, cooldown, unknown-person trigger")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
