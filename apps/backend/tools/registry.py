"""Tool registry — builds the function-declaration surface + dispatches tool calls.

The registry maps ToolName → callable(args, ctx). LiveConnectConfig(tools=[TOOLS_BLOCK])
declares the immutable surface up front (arch decision #2); the router dispatches live
tool_call events to these callables by name and returns their results via send_tool_response.

ToolContext bundles the services + live session state the tools need. Ponytail: a single
dataclass rather than passing services individually to every tool.
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

    # Live observation state (set by the gateway from Working Memory)
    current_context: Any = None  # CurrentContext | None

    # FAISS FaceRepository — wired at RoomSession.create (worker process). When set, the
    # person_service is rebuilt with it so search_by_face / register_face resolve identity.
    face_repo: Any = None  # FaceRepository | None

    # Current conversation session ID — wired by RoomSession so register_person can
    # retroactively link orphan facts from this session to the newly-identified person.
    session_id: str | None = None

    # ponytail: cache the last unknown-face embedding with a TTL. The current_context only
    # holds the last 1s fusion window — if the person walks away mid "siapa ini?" exchange
    # (slow dementia-patient response), the live embedding vanishes and register_face fails
    # with "no face detected". The cache bridges that gap. Full PRD temporary-ID flow
    # (face_recognition.md §11) is Phase 7; this is the minimal fix for the realistic edge.
    _last_unknown_embedding: object = None
    _unknown_embedding_deadline: float = 0.0
    UNKNOWN_EMBEDDING_TTL_S: float = 60.0

    def __post_init__(self) -> None:
        if self.face_repo is not None:
            self.person_service = PersonService(face_repo=self.face_repo)

    def cache_unknown_embedding(self, embedding) -> None:
        """Called by the video loop when an unknown face is detected — bridges the gap
        between face detection and the 1s fusion window so register_face doesn't miss it.
        """
        self._last_unknown_embedding = embedding
        self._unknown_embedding_deadline = time.monotonic() + self.UNKNOWN_EMBEDDING_TTL_S

    def current_face_embedding(self):
        """Return the latest face embedding from the current context, or fall back to cache.

        The recognizer stores the raw embedding on the FaceObservation; the context engine
        keeps the latest. Ponytail: pull from the current context's observations directly
        rather than a separate face cache. Unknown embeddings are cached with a TTL so
        register_face still works after the person leaves frame (slow user response).
        """
        ctx = self.current_context
        if ctx is not None:
            for obs in reversed(getattr(ctx, "observations", [])):
                emb = getattr(obs, "embedding", None)
                if emb is not None:
                    # Refresh cache if this is an unknown face — the one we'd register.
                    if not getattr(obs, "is_known", False):
                        self._last_unknown_embedding = emb
                        self._unknown_embedding_deadline = (
                            time.monotonic() + self.UNKNOWN_EMBEDDING_TTL_S
                        )
                    return emb
        # No live face — use the cached unknown embedding if still fresh.
        if (
            self._last_unknown_embedding is not None
            and time.monotonic() < self._unknown_embedding_deadline
        ):
            return self._last_unknown_embedding
        return None

    def device_snapshot(self) -> dict:
        """Pull device telemetry from the current context's latest DeviceObservation."""
        ctx = self.current_context
        if ctx is None:
            return {}
        for obs in reversed(getattr(ctx, "observations", [])):
            if type(obs).__name__ == "DeviceObservation":
                return {
                    "battery_level": getattr(obs, "battery_level", None),
                    "wifi_connected": getattr(obs, "wifi_connected", None),
                    "button_pressed": getattr(obs, "button_pressed", False),
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
