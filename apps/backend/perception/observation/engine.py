"""Observation engine — fuse a 1s window of observations into a CurrentContext.

perception.md §11: ObservationEngine is the single write path to Working Memory. It drains an
async queue of Observation events, batches them over FUSION_WINDOW_MS, and folds the batch
into one CurrentContext (visible people, scene, activity, speech, device, confidence).

Ponytail: no per-source priority queue — fold in arrival order; the latest of each kind wins
(speech/scene are low-frequency at 1 FPS; ties are fine). Confidence = weighted mean across
the batch (utils.aggregate_confidence).
"""

from __future__ import annotations

import asyncio
import logging

from constants import FUSION_WINDOW_MS
from dto.observations import (
    CurrentContext,
    DeviceObservation,
    FaceObservation,
    Observation,
    SceneObservation,
    SpeechObservation,
)
from perception.observation.working_memory import WorkingMemory
from utils import aggregate_confidence

logger = logging.getLogger(__name__)


class ObservationEngine:
    """Drain observations → fuse per window → write to WorkingMemory."""

    def __init__(
        self,
        working_memory: WorkingMemory,
        *,
        window_ms: int = FUSION_WINDOW_MS,
    ) -> None:
        self.working_memory = working_memory
        self.window_s = window_ms / 1000.0
        self.queue: asyncio.Queue[Observation] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="observation-engine")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def emit(self, observation: Observation) -> None:
        logger.debug("observation queued: %s", type(observation).__name__)
        await self.queue.put(observation)

    async def _run(self) -> None:
        while True:
            batch = await self._collect_window()
            if batch:
                logger.debug("fusing window: %d observation(s)", len(batch))
                ctx = fuse(batch)
                self.working_memory.set(ctx)
                logger.debug(
                    "context updated: people=%s scene=%s speech=%s conf=%.3f",
                    ctx.visible_people,
                    ctx.scene,
                    (ctx.speech or "")[:60],
                    ctx.confidence,
                )

    async def _collect_window(self) -> list[Observation]:
        """Gather observations for one window. First item starts the window."""
        try:
            batch: list[Observation] = [await self.queue.get()]
        except asyncio.CancelledError:
            raise
        deadline = asyncio.get_event_loop().time() + self.window_s
        while asyncio.get_event_loop().time() < deadline:
            timeout = deadline - asyncio.get_event_loop().time()
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=max(0.001, timeout))
                batch.append(item)
            except TimeoutError:
                break
        return batch


def fuse(batch: list[Observation]) -> CurrentContext:
    """Fold a window of observations into one CurrentContext.

    visible_people: dedup names from known FaceObservations (is_known=True). Unknown faces
    surface once as "Orang tidak dikenali" so the agent can ask the user to name them and
    drive register_person/register_face. Latest of each scalar wins; confidence = weighted mean.
    """
    visible: list[str] = []
    seen: set[str] = set()
    scene = activity = speech = device = None
    weights: list[tuple[float, float]] = []  # (confidence, weight)
    unknown_surfaced = False  # one "Orang tidak dikenali" entry per window

    for obs in batch:
        if isinstance(obs, FaceObservation):
            weights.append((obs.confidence, 1.0))
            if obs.is_known and obs.name and obs.name not in seen:
                seen.add(obs.name)
                visible.append(obs.name)
            elif obs.is_possible_match and obs.name:
                # FAISS score 0.60–0.80: probably this person but not confident.
                # Surface as "Mungkin <name>" so the agent can ask "Is this <name>?"
                # and on confirmation, register_face adds the embedding under the
                # existing person_id — improving future matches.
                maybe = f"Mungkin {obs.name}"
                if maybe not in seen:
                    seen.add(maybe)
                    visible.append(maybe)
            elif not obs.is_known and not unknown_surfaced:
                # Fully unknown (score < 0.60) OR possible match with no name resolved
                # (graph down). Surface as "Orang tidak dikenali" so the agent can ask
                # "siapa ini?" and drive the register_person/register_face flow.
                seen.add("Orang tidak dikenali")
                visible.append("Orang tidak dikenali")
                unknown_surfaced = True
        elif isinstance(obs, SceneObservation):
            weights.append((obs.confidence, 1.0))
            if obs.location:
                scene = obs.location
            if obs.activity:
                activity = obs.activity
        elif isinstance(obs, SpeechObservation):
            weights.append((obs.confidence, 1.5))  # speech weighted higher
            if obs.is_final:
                speech = obs.transcript
        elif isinstance(obs, DeviceObservation):
            weights.append((obs.confidence, 0.5))
            device = _device_str(obs)

    return CurrentContext(
        visible_people=visible,
        scene=scene,
        activity=activity,
        speech=speech,
        device=device,
        confidence=aggregate_confidence([c for c, _ in weights], weights=[w for _, w in weights])
        if weights
        else 0.0,
        # ponytail: cap observations to last 10 to prevent unbounded memory growth
        observations=batch[-10:],
    )


def _device_str(d: DeviceObservation) -> str:
    parts = []
    if d.battery_level is not None:
        parts.append(f"baterai {d.battery_level:.0f}%")
    parts.append("wifi " + ("on" if d.wifi_connected else "off"))
    if d.button_pressed:
        parts.append("tombol ditekan")
    return ", ".join(parts)


# --- self-check: fuse a mixed batch ---
def _self_check() -> None:  # pragma: no cover

    batch = [
        FaceObservation(person_id="p1", name="Asep", confidence=0.95, is_known=True),
        FaceObservation(person_id="p2", name="Asep", confidence=0.9, is_known=True),  # dup name
        FaceObservation(
            person_id="p3", name="Budi", confidence=0.7, is_possible_match=True
        ),  # possible match → "Mungkin Budi"
        FaceObservation(person_id=None, name=None, confidence=0.4, is_known=False),  # unknown
        FaceObservation(
            person_id=None, name=None, confidence=0.3, is_known=False
        ),  # 2nd unknown, dedup
        SceneObservation(location="apotek", activity="beli obat", confidence=0.8),
        SpeechObservation(transcript="apa ini?", confidence=0.9, is_final=True),
        DeviceObservation(battery_level=72, wifi_connected=True, confidence=1.0),
    ]
    ctx = fuse(batch)
    # known "Asep" + possible "Mungkin Budi" + one "Orang tidak dikenali" (2nd unknown deduped)
    assert ctx.visible_people == ["Asep", "Mungkin Budi", "Orang tidak dikenali"], (
        ctx.visible_people
    )
    assert ctx.scene == "apotek"
    assert ctx.activity == "beli obat"
    assert ctx.speech == "apa ini?"
    assert "baterai 72%" in ctx.device and "wifi on" in ctx.device
    assert 0.0 < ctx.confidence <= 1.0, ctx.confidence
    print(f"engine fuse self-check OK: people={ctx.visible_people} conf={ctx.confidence:.3f}")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
