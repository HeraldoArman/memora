"""Tool registry — builds the function-declaration surface + dispatches tool calls.

The registry maps ToolName → callable(args, ctx). LiveConnectConfig(tools=[TOOLS_BLOCK])
declares the immutable surface up front (arch decision #2); the router dispatches live
tool_call events to these callables by name and returns their results via send_tool_response.

ToolContext bundles the services + live session state the tools need. Ponytail: a single
dataclass rather than passing services individually to every tool.

refactor/bare-minimum: current_context (CurrentContext from WorkingMemory) is replaced
with last_face — a simple dict written directly by the video loop. No observation engine,
no working memory, no fusion window. Re-enable the observation pipeline by wiring
current_context back and setting it from ObservationEngine.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from schemas import ALL_FUNCTION_DECLARATIONS, TOOLS_BLOCK
from services import (
    EventService,
    KnowledgeService,
    MemoryService,
    PersonService,
    ReminderService,
    ShoppingService,
)

if TYPE_CHECKING:
    pass

ToolFunc = Callable[[dict, "ToolContext"], Any]


@dataclass
class ToolContext:
    """Shared state injected into every tool call."""

    person_service: PersonService = field(default_factory=PersonService)
    memory_service: MemoryService = field(default_factory=MemoryService)
    reminder_service: ReminderService = field(default_factory=ReminderService)
    knowledge_service: KnowledgeService = field(default_factory=KnowledgeService)
    event_service: EventService = field(default_factory=EventService)
    shopping_service: ShoppingService = field(default_factory=ShoppingService)

    # refactor/bare-minimum: direct face result from on-demand ONNX (refresh_face).
    #   {"embedding": np.ndarray, "person_id": str|None, "name": str|None,
    #    "score": float, "is_known": bool, "is_possible": bool}
    last_face: dict | None = None

    # Latest raw video frame (BGR np.ndarray HxWx3 uint8). Written by the video
    # loop every frame; read by refresh_face() only when a tool needs identity.
    last_frame: object = None  # np.ndarray | None

    # Lazy FaceRecognizer singleton — used by refresh_face(). Kept on ToolContext
    # so the ONNX model persists across tool calls (no reload per call).
    _face_recognizer: object = None  # FaceRecognizer | None

    # Step 3: direct scene result from the video loop — SceneUnderstander writes:
    #   {"location": str|None, "objects": list[str], "activity": str|None,
    #    "confidence": float}
    last_scene: dict | None = None

    # Step 5: WorkingMemory holds the fused CurrentContext (30s TTL). When set,
    # device_snapshot() and agent._get_context() prefer it over the raw dicts.
    working_memory: Any = None  # WorkingMemory | None

    # FAISS FaceRepository — wired at RoomSession.create (worker process). When set, the
    # person_service is rebuilt with it so search_by_face / register_face resolve identity.
    face_repo: Any = None  # FaceRepository | None

    # Current conversation session ID — wired by RoomSession so register_person can
    # retroactively link orphan facts from this session to the newly-identified person.
    session_id: str | None = None

    # ponytail: cache the last unknown-face embedding with a TTL. The video loop
    # updates last_face every frame, but if the person walks away mid "siapa ini?"
    # exchange (slow dementia-patient response), last_face goes stale. The cache
    # bridges that gap. Full PRD temporary-ID flow is Phase 7.
    _last_unknown_embedding: object = None
    _unknown_embedding_deadline: float = 0.0
    UNKNOWN_EMBEDDING_TTL_S: float = 60.0

    def __post_init__(self) -> None:
        if self.face_repo is not None:
            self.person_service = PersonService(face_repo=self.face_repo)

    def cache_unknown_embedding(self, embedding) -> None:
        """Called when an unknown face is detected during refresh_face."""
        self._last_unknown_embedding = embedding
        self._unknown_embedding_deadline = time.monotonic() + self.UNKNOWN_EMBEDDING_TTL_S

    async def refresh_face(self) -> None:
        """Run InsightFace on the latest video frame → write to last_face.

        Called on-demand by tools (search_person_by_face, visible_people) so ONNX
        inference runs only when the agent asks "who is this?" — not 30x/minute on
        every frame. Offloaded to a thread so the asyncio event loop (audio pump)
        is never blocked.
        """
        import asyncio

        frame = self.last_frame
        if frame is None:
            return
        if self._face_recognizer is None:
            from perception.face.recognizer import FaceRecognizer

            self._face_recognizer = FaceRecognizer()
        recognizer = self._face_recognizer
        faces = await asyncio.to_thread(recognizer.detect_and_embed, frame)
        if not faces:
            self.last_face = None
            return
        detected = faces[0]
        # FAISS lookup + graph name resolution (reuses existing _update_last_face logic)
        from gateway.livekit.track_handler import _update_last_face

        await _update_last_face(detected, self)

    def current_face_embedding(self):
        """Return the latest face embedding from last_face, or fall back to cache."""
        if self.last_face is not None:
            emb = self.last_face.get("embedding")
            if emb is not None:
                if not self.last_face.get("is_known", False):
                    self._last_unknown_embedding = emb
                    self._unknown_embedding_deadline = (
                        time.monotonic() + self.UNKNOWN_EMBEDDING_TTL_S
                    )
                return emb
        if (
            self._last_unknown_embedding is not None
            and time.monotonic() < self._unknown_embedding_deadline
        ):
            return self._last_unknown_embedding
        return None

    def device_snapshot(self) -> dict:
        """Return device telemetry from WorkingMemory, or {} if unavailable."""
        if self.working_memory is not None:
            ctx = self.working_memory.get()
            if ctx is not None:
                from dto.observations import DeviceObservation

                for obs in ctx.observations:
                    if isinstance(obs, DeviceObservation):
                        return {
                            "battery_level": obs.battery_level,
                            "wifi_connected": obs.wifi_connected,
                            "button_pressed": obs.button_pressed,
                        }
        return {}


# name → ToolFunc registry, populated lazily to avoid import cycles.
_REGISTRY: dict[str, ToolFunc] | None = None


def build_registry() -> dict[str, ToolFunc]:
    """Assemble the name→callable map from every tool module."""
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY
    from tools.calendar.tools import CALENDAR_TOOL_FUNCS
    from tools.knowledge.tools import KNOWLEDGE_TOOL_FUNCS
    from tools.memory.tools import MEMORY_TOOL_FUNCS
    from tools.observation.tools import OBSERVATION_TOOL_FUNCS
    from tools.person.tools import PERSON_TOOL_FUNCS
    from tools.reminder.tools import REMINDER_TOOL_FUNCS
    from tools.system.tools import SYSTEM_TOOL_FUNCS

    _REGISTRY = {
        **PERSON_TOOL_FUNCS,
        **MEMORY_TOOL_FUNCS,
        **REMINDER_TOOL_FUNCS,
        **KNOWLEDGE_TOOL_FUNCS,
        **CALENDAR_TOOL_FUNCS,
        **OBSERVATION_TOOL_FUNCS,
        **SYSTEM_TOOL_FUNCS,
    }
    return _REGISTRY


def get_tool(name: str) -> ToolFunc | None:
    return build_registry().get(name)


# --- self-check: registry covers all declared tools ---
def _self_check() -> None:  # pragma: no cover
    reg = build_registry()
    declared = {d["name"] for d in ALL_FUNCTION_DECLARATIONS}
    implemented = set(reg)
    missing = declared - implemented
    extra = implemented - declared
    # Every declared tool is implemented (knowledge + face-enroll tools included).
    assert not missing, f"declared but not implemented: {sorted(missing)}"
    assert not extra, f"implemented but not declared: {sorted(extra)}"
    assert TOOLS_BLOCK["function_declarations"] is ALL_FUNCTION_DECLARATIONS
    print(f"registry self-check OK: {len(reg)} tools, {len(declared)} declared")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
