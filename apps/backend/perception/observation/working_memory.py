"""Working memory — latest CurrentContext with a 30s TTL.

perception.md §11: a single write path (ObservationEngine) updates this; readers (Context
Engine, Reasoning) read the current snapshot. After MAX_CONTEXT_AGE_MS the context is
considered stale and readers get None — forcing a re-perceive rather than acting on old data.
"""

from __future__ import annotations

import time

from constants import MAX_CONTEXT_AGE_MS
from dto.observations import CurrentContext


class WorkingMemory:
    """Holds the latest CurrentContext; expires after max_age_ms."""

    def __init__(self, *, max_age_ms: int = MAX_CONTEXT_AGE_MS, _clock=time.monotonic) -> None:
        self.max_age_ms = max_age_ms
        self._clock = _clock
        self._context: CurrentContext | None = None
        self._set_at: float = 0.0

    def set(self, context: CurrentContext) -> None:
        self._context = context
        self._set_at = self._clock()

    def get(self) -> CurrentContext | None:
        if self._context is None:
            return None
        if (self._clock() - self._set_at) * 1000 > self.max_age_ms:
            return None  # stale
        return self._context

    @property
    def age_ms(self) -> float:
        if self._context is None:
            return float("inf")
        return (self._clock() - self._set_at) * 1000


# --- self-check ---
def _self_check() -> None:  # pragma: no cover
    wm = WorkingMemory(max_age_ms=100)
    assert wm.get() is None
    ctx = CurrentContext(visible_people=["Asep"])
    wm.set(ctx)
    assert wm.get() is not None
    assert wm.get().visible_people == ["Asep"]

    # fast-forward via injected clock
    class C:
        t = 0.0

    w = WorkingMemory(max_age_ms=100, _clock=lambda: C.t)
    C.t = 1.0
    w.set(ctx)
    C.t = 1.05
    assert w.get() is not None  # 50ms < 100ms
    C.t = 1.2
    assert w.get() is None  # 200ms > 100ms stale
    print("working_memory self-check OK")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
