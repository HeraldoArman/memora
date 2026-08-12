# AgentSession Refactor — Implementation Plan

**Branch:** `refactor/agent-session-gemini`
**Base:** `refactor/bare-minimum` (commit `0e9649f`)
**Date:** 2026-08-12
**Status:** Not started — plan only, no code written yet

> **Context for a new session:** This document is the complete implementation
> guide for refactoring the Memora backend from a custom `GeminiLiveSession`
> WebSocket plumbing to LiveKit's `AgentSession` + `google.realtime.RealtimeModel`
> plugin. Read this document in full before starting. All research is done;
> the architecture is decided; the file-by-file changes are specified below
> with enough detail to implement without re-reading the codebase.

---

## Why

The custom `GeminiLiveSession` caused:

1. **Audio race condition:** `SpeechForwarder` started before Gemini connected →
   mic frames silently dropped (`_session is None` → `return`). Audio buffering
   was attempted but made things worse — stale audio flooded Gemini on reconnect.
2. **Reconnect feedback loop:** `_recent_turns` re-injection → model responds to
   its own old text → new turn → re-injected → infinite loop. Model never
   processed live audio. Zero `input_transcription` events in entire sessions.
3. **No video to Gemini:** Camera went to InsightFace only. Gemini couldn't see
   the scene — only identify faces via tool calls.
4. **~900 lines of fragile custom plumbing** that LiveKit handles natively.

---

## What

Replace custom plumbing with LiveKit's `AgentSession` +
`google.realtime.RealtimeModel`. The framework handles audio/video streaming,
WebSocket lifecycle, reconnection, VAD-based turn detection, tool dispatch, and
audio output — all natively.

Gemini sees the camera and hears the mic **directly**. Tools are called
on-demand via `@function_tool` decorator. InsightFace runs in parallel for
face recognition → `tool_ctx.last_face` (same as before).

---

## Architecture

### Before (custom plumbing)

```
mic → SpeechForwarder → _AudioShim → GeminiLiveSession.send_audio → Gemini WS
camera → FrameSampler → InsightFace → tool_ctx.last_face (tool only)
text prompt → data_received → agent.feed_prompt → GeminiLiveSession.send_text
Gemini WS → receive_loop → on_text → Display → data channel "display"
Gemini WS → receive_loop → audio blob → Speaker → AudioSource → room
Gemini WS → receive_loop → tool_call → ToolRouter → send_tool_response
extraction → on_turn_complete (turn_complete event) → PipelineRunner
```

### After (AgentSession + RealtimeModel)

```
mic → LiveKit → AgentSession → Gemini RealtimeModel (audio, direct)
camera → LiveKit → AgentSession → Gemini RealtimeModel (video, direct, 1 FPS)
camera → LiveKit → track_handler video loop → InsightFace → tool_ctx.last_face
text prompt → data_received → session.generate_reply()
Gemini → AgentSession → audio output (automatic → LiveKit audio track)
Gemini → AgentSession → conversation_item_added event → Display (OLED)
Gemini → AgentSession → tool_call → @function_tool methods on MemoraAgent
extraction → on_user_turn_completed hook → PipelineRunner
```

---

## Dependencies

### Install

Add `livekit-agents[google]` extra to `apps/backend/pyproject.toml`:

```toml
# Current:
"livekit-agents==1.6.9",
# Change to:
"livekit-agents[google]==1.6.9",
```

Then `uv sync` in `apps/backend/`.

**Verify the plugin imports:**

```bash
cd apps/backend && uv run python -c "from livekit.plugins import google; print('OK')"
```

**If this fails on Python 3.14:** Check if the google plugin has a Python
version constraint. The venv is at `.venv/` (Python 3.14). If incompatible,
you may need to recreate the venv with Python 3.12 or install the plugin
manually. Check `uv python list` for available versions.

### Already available (verified)

- `livekit.agents.Agent` — at `livekit/agents/voice/agent.py`
- `livekit.agents.AgentSession` — at `livekit/agents/voice/agent_session.py`
- `livekit.agents.function_tool` — at `livekit/agents/__init__.py:59`
- `livekit.agents.RunContext` — at `livekit/agents/__init__.py:98`
- `livekit.agents.room_io.RoomOptions` — at `livekit/agents/voice/room_io/__init__.py`
- `room_io.RoomOptions(video_input=True)` — confirmed available
- `room_io.RoomOptions(text_output=TextOutputOptions(...))` — confirmed available

---

## Files Overview

### Files to CREATE or REWRITE

| File                                            | Action       | ~Lines          |
| ----------------------------------------------- | ------------ | --------------- |
| `apps/backend/reasoning/agent/agent.py`         | **Rewrite**  | ~200            |
| `apps/backend/gateway/livekit/entrypoint.py`    | **Rewrite**  | ~120            |
| `apps/backend/gateway/livekit/track_handler.py` | **Simplify** | ~100 (from 214) |

### Files to DELETE

| File                                             | Lines | Replaced by                  |
| ------------------------------------------------ | ----- | ---------------------------- |
| `apps/backend/reasoning/session/live_session.py` | ~660  | `RealtimeModel` plugin       |
| `apps/backend/reasoning/session/__init__.py`     | ~2    | (was just re-export)         |
| `apps/backend/reasoning/tools/router.py`         | ~90   | `@function_tool` decorator   |
| `apps/backend/reasoning/response/speaker.py`     | ~100  | `AgentSession` audio output  |
| `apps/backend/perception/speech/forwarder.py`    | ~60   | `AgentSession` audio input   |
| `apps/backend/gateway/session.py`                | ~130  | Inlined into `entrypoint.py` |

### Files UNCHANGED

| File                                           | Notes                                                                                                             |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `apps/backend/reasoning/response/display.py`   | Keep as-is — still publishes to "display" topic                                                                   |
| `apps/backend/tools/registry.py`               | Keep `ToolContext` dataclass. `build_registry()` / `get_tool()` no longer used by agent but may be used by tests. |
| `apps/backend/tools/person/tools.py`           | Keep all tool functions. They're called from `@function_tool` wrappers.                                           |
| `apps/backend/tools/memory/tools.py`           | Same                                                                                                              |
| `apps/backend/tools/reminder/tools.py`         | Same                                                                                                              |
| `apps/backend/tools/knowledge/tools.py`        | Same                                                                                                              |
| `apps/backend/tools/calendar/tools.py`         | Same                                                                                                              |
| `apps/backend/tools/observation/tools.py`      | Same                                                                                                              |
| `apps/backend/tools/system/tools.py`           | Same                                                                                                              |
| `apps/backend/perception/face/recognizer.py`   | Keep — InsightFace adapter                                                                                        |
| `apps/backend/perception/vision/sampler.py`    | Keep — FrameSampler for video loop                                                                                |
| `apps/backend/reasoning/prompts/system.py`     | Keep — `build_system_instruction()`                                                                               |
| `packages/shared/prompts/system.py`            | Keep — `SYSTEM_INSTRUCTION` text                                                                                  |
| `packages/shared/schemas/__init__.py`          | Keep — `TOOLS_BLOCK`, `ALL_FUNCTION_DECLARATIONS`                                                                 |
| `apps/backend/workers/livekit_worker.py`       | Keep — but remove `from gateway.session import RoomSession` if referenced                                         |
| `apps/backend/pipeline/runner.py`              | Keep — `PipelineRunner` for extraction                                                                            |
| `apps/backend/gateway/livekit/data_channel.py` | Keep — `parse_device_telemetry` (not actively used but kept for Step 5)                                           |
| All test files                                 | Keep — update imports if they reference deleted files                                                             |
| Dashboard code                                 | No changes needed                                                                                                 |

### Files that need IMPORT FIXES

Any file that imports from deleted modules:

- `reasoning/session/__init__.py` — re-exports `GeminiLiveSession`, delete or clear
- `reasoning/agent/__init__.py` — re-exports `ReasoningAgent`, update to `MemoraAgent`
- `gateway/__init__.py` — may reference `RoomSession`
- `gateway/session.py` — being deleted, but check for reverse imports
- Test files that import `GeminiLiveSession`, `SpeechForwarder`, `Speaker`, `RoomSession`, `ToolRouter`
- `workers/livekit_worker.py` — imports `entrypoint` (which is being rewritten, but the import path stays the same)

**Search for all references to deleted modules before deleting:**

```bash
cd apps/backend && grep -rn "live_session\|GeminiLiveSession\|SpeechForwarder\|Speaker\|RoomSession\|dispatch_tool_call\|router" --include="*.py" | grep -v __pycache__ | grep -v ".pyc"
```

---

## Detailed Implementation

### Step 0: Install dependency

```bash
cd apps/backend
# Edit pyproject.toml: "livekit-agents==1.6.9" → "livekit-agents[google]==1.6.9"
uv sync
uv run python -c "from livekit.plugins import google; print('OK')"
```

If the `google` extra doesn't resolve, try:

```bash
uv add "livekit-agents[google]==1.6.9"
```

### Step 1: Write new `MemoraAgent` (`reasoning/agent/agent.py`)

This is the biggest file. It replaces `ReasoningAgent` with a LiveKit `Agent`
subclass that has all tools as `@function_tool` methods.

**Key design decisions:**

1. **ToolContext as instance state:** The `ToolContext` (with `face_repo`,
   `person_service`, `memory_service`, `last_face`, `session_id`, etc.) is
   passed to the constructor and stored as `self._tool_ctx`. All `@function_tool`
   methods access it via `self._tool_ctx`.

2. **Tool functions stay in `tools/` modules:** The actual tool logic
   (`search_person`, `get_person`, `register_face`, etc.) stays in
   `tools/person/tools.py`, `tools/memory/tools.py`, etc. The `@function_tool`
   methods on `MemoraAgent` are thin wrappers that call the existing functions.

3. **Display via `conversation_item_added` event:** Listen to the
   `AgentSession`'s `conversation_item_added` event. When an assistant message
   is added, publish its text to the "display" topic via `Display.show()`.

4. **Extraction via `on_user_turn_completed`:** Override this hook to run
   `PipelineRunner` after each user turn.

5. **Prompt handling:** The `data_received` handler in `entrypoint.py` calls
   `session.generate_reply(instructions=prompt_text)` for "prompt" topic
   messages. This replaces `agent.feed_prompt()`.

**Full code structure:**

```python
"""MemoraAgent — LiveKit Agent subclass with Gemini RealtimeModel tools.

Replaces the custom GeminiLiveSession + ReasoningAgent + ToolRouter with a
single Agent class that uses LiveKit's @function_tool decorator. Audio, video,
reconnection, VAD-based turn detection, and audio output are handled by
AgentSession + RealtimeModel — no custom plumbing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from livekit.agents import Agent, AgentSession, RunContext, function_tool

from prompts import SYSTEM_INSTRUCTION
from reasoning.response.display import Display
from tools import ToolContext

log = logging.getLogger(__name__)


class MemoraAgent(Agent):
    """LiveKit Agent for Memora — dementia memory assistant.

    Tools are exposed via @function_tool decorator. The agent sees video
    directly (via RoomOptions.video_input=True) and hears audio directly
    (via AgentSession). InsightFace runs in parallel for face recognition,
    writing results to tool_ctx.last_face.
    """

    def __init__(
        self,
        *,
        tool_ctx: ToolContext,
        display: Display,
        on_extract: Any = None,  # Callable[[str, str | None], Awaitable[None]]
    ) -> None:
        super().__init__(instructions=SYSTEM_INSTRUCTION)
        self._tool_ctx = tool_ctx
        self._display = display
        self._on_extract = on_extract

    async def on_enter(self) -> None:
        """Called when agent becomes active. Greet the user."""
        await self.session.generate_reply(
            instructions="Sapa pengguna dengan singkat dalam Bahasa Indonesia."
        )

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        """Called after user's turn ends. Trigger memory extraction."""
        if self._on_extract is None:
            return
        # Build text from the latest user message + any agent response
        text = new_message.text_content or ""
        if not text:
            return
        try:
            await self._on_extract(text, self._tool_ctx.session_id)
        except Exception as exc:
            log.warning("on_extract failed: %s", exc)

    # --- Person tools ---

    @function_tool()
    async def visible_people(self, ctx: RunContext) -> dict:
        """Return currently visible person from face recognition.

        Uses InsightFace results written by the video loop to tool_ctx.last_face.
        """
        f = self._tool_ctx.last_face
        if not f:
            return {"people": []}
        return {
            "people": [
                {
                    "name": f.get("name"),
                    "person_id": f.get("person_id"),
                    "known": f.get("is_known", False),
                    "possible": f.get("is_possible", False),
                    "score": f.get("score", 0.0),
                }
            ]
        }

    @function_tool()
    async def search_person(self, ctx: RunContext, query: str) -> dict:
        """Search people by name substring (graph).

        Args:
            query: The name or partial name to search for.
        """
        from tools.person.tools import search_person as _search_person

        return await _search_person({"query": query}, self._tool_ctx)

    @function_tool()
    async def get_person(self, ctx: RunContext, person_id: str) -> dict:
        """Get a person's full profile: name, notes, and relationships.

        Args:
            person_id: The person ID to look up.
        """
        from tools.person.tools import get_person as _get_person

        return await _get_person({"person_id": person_id}, self._tool_ctx)

    @function_tool()
    async def search_person_by_face(self, ctx: RunContext) -> dict:
        """Identify the currently visible person via face recognition."""
        from tools.person.tools import search_person_by_face as _search_by_face

        return await _search_by_face({}, self._tool_ctx)

    @function_tool()
    async def register_person(self, ctx: RunContext, name: str) -> dict:
        """Register a new person by name.

        Args:
            name: The person's name.
        """
        from tools.person.tools import register_person as _register_person

        return await _register_person({"name": name}, self._tool_ctx)

    @function_tool()
    async def register_face(self, ctx: RunContext, person_id: str) -> dict:
        """Link the currently visible face to an existing person.

        Args:
            person_id: The person ID to link the face to.
        """
        from tools.person.tools import register_face as _register_face

        return await _register_face({"person_id": person_id}, self._tool_ctx)

    @function_tool()
    async def update_person(self, ctx: RunContext, person_id: str, notes: str) -> dict:
        """Update a person's notes.

        Args:
            person_id: The person ID to update.
            notes: The new notes content.
        """
        from tools.person.tools import update_person as _update_person

        return await _update_person({"person_id": person_id, "notes": notes}, self._tool_ctx)

    # --- Memory tools ---

    @function_tool()
    async def search_memory(self, ctx: RunContext, query: str) -> dict:
        """Search episodic memory for relevant past interactions.

        Args:
            query: The search query.
        """
        from tools.memory.tools import search_memory as _search_memory

        return await _search_memory({"query": query}, self._tool_ctx)

    @function_tool()
    async def conversation_summary(self, ctx: RunContext) -> dict:
        """Get a summary of recent conversation history."""
        from tools.memory.tools import conversation_summary as _conv_summary

        return await _conv_summary({}, self._tool_ctx)

    @function_tool()
    async def memory_timeline(self, ctx: RunContext) -> dict:
        """Get a chronological timeline of recent memories."""
        from tools.memory.tools import memory_timeline as _memory_timeline

        return await _memory_timeline({}, self._tool_ctx)

    # --- Reminder tools ---

    @function_tool()
    async def create_reminder(self, ctx: RunContext, content: str, time: str) -> dict:
        """Create a reminder.

        Args:
            content: What to remind about.
            time: When to remind (ISO format or natural language).
        """
        from tools.reminder.tools import create_reminder as _create_reminder

        return await _create_reminder({"content": content, "time": time}, self._tool_ctx)

    @function_tool()
    async def list_reminders(self, ctx: RunContext) -> dict:
        """List all pending reminders."""
        from tools.reminder.tools import list_reminders as _list_reminders

        return await _list_reminders({}, self._tool_ctx)

    # --- Knowledge tools ---

    @function_tool()
    async def search_knowledge(self, ctx: RunContext, query: str) -> dict:
        """Search the knowledge graph for entities and facts.

        Args:
            query: The search query.
        """
        from tools.knowledge.tools import search_knowledge as _search_knowledge

        return await _search_knowledge({"query": query}, self._tool_ctx)

    # --- Calendar tools ---

    @function_tool()
    async def create_event(
        self, ctx: RunContext, title: str, start_time: str, end_time: str = ""
    ) -> dict:
        """Create a calendar event.

        Args:
            title: Event title.
            start_time: Start time (ISO format).
            end_time: End time (ISO format, optional).
        """
        from tools.calendar.tools import create_event as _create_event

        return await _create_event(
            {"title": title, "start_time": start_time, "end_time": end_time}, self._tool_ctx
        )

    @function_tool()
    async def list_events(self, ctx: RunContext) -> dict:
        """List upcoming calendar events."""
        from tools.calendar.tools import list_events as _list_events

        return await _list_events({}, self._tool_ctx)

    # --- Shopping tools ---

    @function_tool()
    async def add_shopping_item(self, ctx: RunContext, item: str) -> dict:
        """Add an item to the shopping list.

        Args:
            item: The item to add.
        """
        from tools.reminder.tools import add_shopping_item as _add_shopping

        return await _add_shopping({"item": item}, self._tool_ctx)

    @function_tool()
    async def list_shopping_items(self, ctx: RunContext) -> dict:
        """List all shopping list items."""
        from tools.reminder.tools import list_shopping_items as _list_shopping

        return await _list_shopping({}, self._tool_ctx)

    # --- System tools ---

    @function_tool()
    async def firmware_version(self, ctx: RunContext) -> dict:
        """Get the device firmware version."""
        from tools.system.tools import firmware_version as _firmware_version

        return await _firmware_version({}, self._tool_ctx)

    # --- Observation tools ---

    @function_tool()
    async def current_scene(self, ctx: RunContext) -> dict:
        """Get the current scene/location analysis."""
        from tools.observation.tools import current_scene as _current_scene

        return await _current_scene({}, self._tool_ctx)

    @function_tool()
    async def current_activity(self, ctx: RunContext) -> dict:
        """Get the current activity being performed."""
        from tools.observation.tools import current_activity as _current_activity

        return await _current_activity({}, self._tool_ctx)
```

**IMPORTANT — verify tool function signatures:** The existing tool functions
in `tools/*/tools.py` take `(args: dict, ctx: ToolContext)`. The `@function_tool`
wrappers extract typed parameters and call the existing functions with a dict.
Before finalizing, read EVERY tool file to verify the exact function names and
argument schemas:

```bash
cd apps/backend && grep -n "^async def\|^def\|_TOOL_FUNCS" tools/*/tools.py
```

Also check `packages/shared/schemas/tools.py` for the complete list of declared
tools and their parameter schemas — every declared tool must have a
corresponding `@function_tool` method on `MemoraAgent`:

```bash
cd apps/backend && uv run python -c "from schemas import ALL_FUNCTION_DECLARATIONS; [print(d['name']) for d in ALL_FUNCTION_DECLARATIONS]"
```

**IMPORTANT — tool function availability:** Some tool functions may not exist
yet (e.g., `add_shopping_item`, `list_shopping_items`, `search_knowledge`,
`create_event`, `list_events`). Check what's actually in each tool module:

```bash
cd apps/backend && grep -n "TOOL_FUNCS\|async def" tools/calendar/tools.py tools/knowledge/tools.py tools/reminder/tools.py tools/observation/tools.py tools/system/tools.py
```

If a tool function doesn't exist, either:

- Skip that `@function_tool` method (the model won't see it)
- Or create a stub that returns `{"available": False}`

**IMPORTANT — tool imports:** The existing tool functions import from
`tools.registry` for `ToolContext`. This import stays valid since
`ToolContext` is kept in `registry.py`. The functions themselves don't
change — only how they're called (from `@function_tool` wrapper instead of
`ToolRouter`).

---

### Step 2: Write new `entrypoint.py` (`gateway/livekit/entrypoint.py`)

This replaces the current entrypoint. It creates the `AgentSession`, configures
the `RealtimeModel`, starts the InsightFace video loop, and wires the display
event handler.

**Full code structure:**

```python
"""LiveKit agent entrypoint — AgentSession + Gemini RealtimeModel.

Replaces the custom GeminiLiveSession plumbing with LiveKit's AgentSession +
google.realtime.RealtimeModel. Audio, video, reconnection, VAD-based turn
detection, and audio output are handled by the framework.

InsightFace runs in parallel via track_handler for face recognition →
tool_ctx.last_face. Gemini sees video directly via RoomOptions(video_input=True).
"""

from __future__ import annotations

import asyncio
import logging

from livekit import rtc
from livekit.agents import JobContext, AgentSession, room_io
from livekit.plugins import google

from gateway.livekit.track_handler import handle_video_track
from reasoning.agent.agent import MemoraAgent
from reasoning.response.display import Display
from tools import ToolContext

log = logging.getLogger(__name__)


async def entrypoint(ctx: JobContext) -> None:
    """Per-room job: build AgentSession with Gemini RealtimeModel."""
    room = ctx.room

    # The worker is a separate process — wire Postgres + Neo4j here.
    await _init_stores()

    # Connect to the room FIRST so we don't miss early prompts/tracks.
    await ctx.connect(auto_subscribe=True)
    log.info("job connected to room %s (participants=%d)", room.name, len(room.remote_participants))

    # --- Build tool context (same as old RoomSession.create) ---
    from env import get_settings
    from vector.repository import FaceRepository

    settings = get_settings()
    face_repo = await FaceRepository.from_db(
        known_threshold=settings.face_match_threshold,
        possible_threshold=settings.face_possible_match_threshold,
        dim=settings.face_embedding_dim,
    )
    tool_ctx = ToolContext(face_repo=face_repo)

    # Start conversation session for episodic memory
    session_id = None
    try:
        from services import MemoryService

        session_id = await MemoryService().start_session(summary="livekit room")
        tool_ctx.session_id = session_id
        log.info("conversation session started: %s", session_id)
    except Exception:
        log.warning("conversation session start failed; episodic memory unavailable")

    log.info("room session face repo ready: %d embedding(s)", face_repo.size)

    # Preload InsightFace in background thread
    import asyncio as _aio
    from perception.face.recognizer import preload as preload_face

    _aio.get_event_loop().run_in_executor(None, preload_face)

    # Wire extraction pipeline
    async def _on_extract(text: str, sid: str | None) -> None:
        from pipeline.runner import PipelineRunner

        await PipelineRunner().run(text, session_id=sid)

    # --- Create display ---
    display = Display(room)

    # --- Create agent ---
    agent = MemoraAgent(
        tool_ctx=tool_ctx,
        display=display,
        on_extract=_on_extract,
    )

    # --- Create AgentSession with Gemini RealtimeModel ---
    session = AgentSession(
        llm=google.realtime.RealtimeModel(
            model=settings.gemini_live_model,
            voice="Puck",
        ),
    )

    # --- Wire display: publish agent responses to OLED ---
    @session.on("conversation_item_added")
    def _on_conversation_item(ev):
        # ev.message has role + content. Only publish assistant messages.
        # Check the event structure — may need to inspect ev.message.role
        # and extract text from ev.message.content
        try:
            msg = ev.message
            if msg.role == "assistant":
                text = msg.text_content or ""
                if text:
                    asyncio.create_task(display.show(text))
        except Exception:
            log.debug("conversation_item_added parse failed", exc_info=True)

    # --- Wire track handlers for InsightFace (video only) ---
    @room.on("track_subscribed")
    def _on_track(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        if publication.kind == rtc.TrackKind.KIND_VIDEO:
            task = asyncio.create_task(handle_video_track(track, room, tool_ctx))
            log.info("video track subscribed from %s", participant.identity)

    # Subscribe to existing participant tracks
    for p in room.remote_participants.values():
        for pub in p.track_publications.values():
            if not pub.subscribed:
                pub.set_subscribed(True)
            if pub.subscribed and pub.track and pub.kind == rtc.TrackKind.KIND_VIDEO:
                task = asyncio.create_task(handle_video_track(pub.track, room, tool_ctx))
                log.info("video track subscribed from %s (existing)", p.identity)

    # --- Wire data channel for text prompts ---
    @room.on("data_received")
    def _on_data(packet: rtc.DataPacket):
        topic = packet.topic or ""
        data = bytes(packet.data)
        if topic == "prompt":
            text = data.decode("utf-8", errors="replace")
            log.info("prompt received: %r — generating reply", text)
            asyncio.create_task(session.generate_reply(instructions=text))
        elif topic == "device":
            log.debug("device telemetry: %r", data[:200])

    # --- Start the session ---
    await session.start(
        room=room,
        agent=agent,
        room_options=room_io.RoomOptions(
            video_input=True,
            audio_input=True,
            text_output=room_io.TextOutputOptions(
                sync_transcription=False,
            ),
        ),
    )
    log.info("agent session started")

    # --- Wait until the job ends ---
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        await session.aclose()
        log.info("room session torn down for %s", room.name)


async def _init_stores() -> None:
    """Wire Postgres + Neo4j for this worker process."""
    from env import get_settings
    from graph import client as neo4j_client
    from postgres import session as pg_session

    settings = get_settings()
    try:
        pg_session.init_engine(settings.database_url)
    except Exception:
        log.exception("postgres init failed; memory persistence unavailable")
    try:
        await neo4j_client.init_driver(
            settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password
        )
    except Exception:
        log.exception("neo4j init failed; graph + face-name lookup unavailable")
```

**IMPORTANT — verify `conversation_item_added` event structure:** The exact
event payload shape needs verification. Check the LiveKit docs reference at
`https://docs.livekit.io/reference/agents/events.md#conversation_item_added`
or inspect the installed source:

```bash
grep -r "conversation_item_added\|ConversationItemAdded" .venv/lib/python3.14/site-packages/livekit/agents/ --include="*.py"
```

The event may have `.message` with `.role` and `.content` or `.text_content`.
Adapt the handler accordingly.

**IMPORTANT — `handle_video_track` signature change:** The current
`handle_video_track(track, room, session)` takes a `RoomSession` (which has
`.tool_ctx` and `.face_repo`). Since `RoomSession` is being deleted, change
the signature to `handle_video_track(track, room, tool_ctx)` — pass
`tool_ctx` directly. Update the function in `track_handler.py` accordingly.

---

### Step 3: Simplify `track_handler.py` (`gateway/livekit/track_handler.py`)

**Remove:**

- `_AudioShim` class (entirely)
- `handle_audio_track()` function (entirely)

**Keep and modify:**

- `handle_video_track()` — change signature from `(track, room, session)` to
  `(track, room, tool_ctx)`. Replace `session.tool_ctx` with `tool_ctx` and
  `session.face_repo` with `tool_ctx.face_repo`.

**The `_update_last_face` function** currently takes `session` and accesses
`session.face_repo` and `session.tool_ctx`. Change it to take `tool_ctx`
directly:

- `session.face_repo` → `tool_ctx.face_repo`
- `session.tool_ctx.last_face` → `tool_ctx.last_face`
- `session.tool_ctx.cache_unknown_embedding(...)` → `tool_ctx.cache_unknown_embedding(...)`

**Updated `handle_video_track`:**

```python
async def handle_video_track(track, room, tool_ctx) -> asyncio.Task:
    """Spawn the video loop: sample frames → face identity.

    Returns the background task (caller stores it for cleanup).
    """
    from livekit import rtc
    from perception.face.recognizer import FaceRecognizer
    from perception.vision.sampler import FrameSampler

    video_stream = rtc.VideoStream(track)
    sampler = FrameSampler(video_stream)
    recognizer = FaceRecognizer()

    async def _video_loop() -> None:
        log.info("video loop started")
        frame_count = 0
        try:
            async for frame in sampler.frames():
                frame_count += 1
                try:
                    bgr = frame["bgr"]
                    faces = await asyncio.to_thread(recognizer.detect_and_embed, bgr)
                    log.info("frame: %dx%d faces=%d", bgr.shape[1], bgr.shape[0], len(faces))
                    if faces:
                        await _update_last_face(faces[0], tool_ctx)
                    del bgr, faces
                    if frame_count % 5 == 0:
                        gc.collect()
                except Exception:
                    log.exception("face recognize failed")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("video loop crashed")

    task = asyncio.create_task(_video_loop(), name="video-loop")
    return task
```

**Updated `_update_last_face`:**

```python
async def _update_last_face(detected, tool_ctx) -> None:
    """Look up face embedding → write result directly to tool_ctx.last_face."""
    try:
        face_repo = tool_ctx.face_repo
        if face_repo is None:
            log.debug("face repo not available; skipping identity lookup")
            return
        result = face_repo.lookup(detected.embedding)
        name = None
        if result.person_id and (result.is_known or result.is_possible):
            try:
                from graph import repository as graph_repo

                profile = await graph_repo.PersonRepo().get_person(result.person_id)
                if profile:
                    name = profile.get("name")
            except Exception:
                log.warning("face name lookup failed for %s; keeping name=None", result.person_id)

        if result.person_id is None:
            log.info("face lookup: unknown score=%.3f", result.score)
        else:
            log.info(
                "face lookup: %s name=%s score=%.3f known=%s possible=%s",
                result.person_id,
                name,
                result.score,
                result.is_known,
                result.is_possible,
            )

        tool_ctx.last_face = {
            "embedding": detected.embedding,
            "person_id": result.person_id,
            "name": name,
            "score": float(result.score),
            "is_known": result.is_known,
            "is_possible": result.is_possible,
        }
        if not result.is_known:
            tool_ctx.cache_unknown_embedding(detected.embedding)
    except Exception:
        log.exception("face lookup failed")
```

**Update the self-check** at the bottom of the file — remove the `_AudioShim`
test, keep the video-related tests.

---

### Step 4: Delete dead files

```bash
cd apps/backend

# Delete files
rm reasoning/session/live_session.py
rm reasoning/session/__init__.py   # was just `from .live_session import GeminiLiveSession`
rm reasoning/tools/router.py
rm reasoning/response/speaker.py
rm perception/speech/forwarder.py
rm gateway/session.py

# Check for broken imports
grep -rn "live_session\|GeminiLiveSession\|SpeechForwarder\|Speaker\|RoomSession\|dispatch_tool_call\|router" --include="*.py" | grep -v __pycache__ | grep -v ".pyc" | grep -v test
```

**Fix any remaining imports:**

- `reasoning/session/` — if the directory is now empty (after deleting
  `__init__.py` and `live_session.py`), remove the directory:
  `rmdir reasoning/session/`
- `reasoning/agent/__init__.py` — update from `ReasoningAgent` to `MemoraAgent`
- `reasoning/tools/__init__.py` — remove `get_tool` if it references `router.py`
  (actually `get_tool` is in `registry.py`, not `router.py`, so this may be fine)
- `workers/livekit_worker.py` — check if it imports `RoomSession` (it imports
  `entrypoint` which is being rewritten, so the import path stays the same)
- Any test file that imports deleted modules — update or skip those tests

---

### Step 5: Fix test imports

Search for all test files that reference deleted modules:

```bash
cd apps/backend && grep -rn "live_session\|GeminiLiveSession\|SpeechForwarder\|Speaker\|RoomSession\|dispatch_tool_call\|reasoning.tools.router\|reasoning.session\|reasoning.response.speaker\|perception.speech.forwarder\|gateway.session" tests/ --include="*.py"
```

For each match:

- If the test tests a deleted module, delete or skip the test
- If the test imports a deleted module incidentally, update the import

**Key test files likely affected:**

- `tests/unit/test_reasoning.py` — tests `ReasoningAgent`, likely imports
  `GeminiLiveSession`, `Speaker`, etc. Needs rewrite to test `MemoraAgent`
  with mocked `AgentSession`.
- `tests/unit/test_gateway.py` — tests `RoomSession.create()`. Needs rewrite
  or deletion since `RoomSession` is gone.
- `tests/unit/test_live_session.py` (if exists) — delete entirely
- `tests/unit/test_forwarder.py` (if exists) — delete entirely
- `tests/unit/test_speaker.py` (if exists) — delete entirely
- `tests/unit/test_router.py` (if exists) — delete entirely

**Strategy:** Run `uv run pytest tests/ -x` after each step and fix failures
incrementally. Don't try to fix all tests upfront — get the main code working
first, then fix tests.

---

### Step 6: Update `reasoning/agent/__init__.py`

```python
from reasoning.agent.agent import MemoraAgent

__all__ = ["MemoraAgent"]
```

### Step 7: Update `reasoning/session/` directory

If `reasoning/session/__init__.py` and `live_session.py` are the only files:

```bash
rm -rf apps/backend/reasoning/session/
```

Then fix any imports of `reasoning.session`:

```bash
grep -rn "reasoning.session\|from reasoning.session" --include="*.py" apps/backend/ | grep -v __pycache__
```

### Step 8: Update `reasoning/tools/__init__.py`

Check if it imports from `router.py`:

```python
# Current:
from tools.registry import ToolContext, build_registry, get_tool

__all__ = ["ToolContext", "build_registry", "get_tool"]
```

This imports from `registry.py`, not `router.py`, so it should be fine. But
verify `registry.py` doesn't import from `router.py`:

```bash
grep -n "router" apps/backend/tools/registry.py
```

---

## Implementation Order

1. **Install dependency** (Step 0) — `uv sync`, verify import
2. **Write `MemoraAgent`** (Step 1) — the new agent class with all `@function_tool` methods
3. **Simplify `track_handler.py`** (Step 3) — remove audio, update video signature
4. **Write new `entrypoint.py`** (Step 2) — AgentSession + RealtimeModel + wiring
5. **Update `__init__.py` files** (Steps 6, 7, 8)
6. **Delete dead files** (Step 4)
7. **Fix test imports** (Step 5) — run `uv run pytest tests/ -x`, fix iteratively
8. **Run self-checks** — `uv run python -m reasoning.agent.agent` etc.
9. **Live test** — `bun run dev`, connect via dashboard, verify audio + video + tools

---

## Verification Checklist

After implementation, verify each item:

### Static checks

- [ ] `uv run python -c "from livekit.plugins import google; print('OK')"` — plugin installed
- [ ] `uv run python -c "from reasoning.agent.agent import MemoraAgent; print('OK')"` — agent imports
- [ ] `uv run python -c "from gateway.livekit.entrypoint import entrypoint; print('OK')"` — entrypoint imports
- [ ] `uv run pytest tests/ -x` — all tests pass (or at least no new failures)
- [ ] `grep -rn "GeminiLiveSession\|SpeechForwarder\|Speaker\|RoomSession" --include="*.py" apps/backend/ | grep -v __pycache__ | grep -v test` — no stale references

### Live checks (via `bun run dev`)

- [ ] Worker registers with LiveKit Cloud
- [ ] Dashboard connects, token minted
- [ ] Job dispatched to worker
- [ ] AgentSession starts with RealtimeModel
- [ ] **Speak into mic** → agent hears and responds (audio output)
- [ ] **Check logs** → `input_transcription` events present (audio reaching Gemini)
- [ ] **Check logs** → no reconnect loops (no repeated "gemini live connected" + "re-injected")
- [ ] Send text prompt "halo" → agent responds with audio + display text
- [ ] Send "ini siapa" → agent calls `visible_people` tool
- [ ] Point camera at face → InsightFace recognizes → agent identifies
- [ ] Display shows agent response text on OLED

### What "fixed" looks like in logs

**Before (broken):**

```
flushed 1000 pending audio chunk(s) (~10.0s)
re-injected 6 recent turn(s) after reconnect
gemini live reconnected
model reasoning: **Acknowledge Previous Interaction**
(never any input_transcription events)
```

**After (working):**

```
agent session started
(user speaks)
input_transcription: "halo, apa kabar"
(agent responds)
conversation_item_added: role=assistant text="Halo! Ada yang bisa saya bantu?"
display.show → publish topic=display
(no reconnect loops, no re-injection, no audio buffering)
```

---

## Key References

- **LiveKit Gemini plugin docs:** https://docs.livekit.io/agents/models/realtime/plugins/gemini.md
- **LiveKit AgentSession docs:** https://docs.livekit.io/agents/logic/sessions.md
- **LiveKit function_tool docs:** https://docs.livekit.io/agents/logic/tools/definition.md
- **LiveKit video input docs:** https://docs.livekit.io/agents/multimodality/vision/video.md
- **LiveKit nodes/hooks docs:** https://docs.livekit.io/agents/build/nodes.md
- **Gemini Live vision recipe:** https://docs.livekit.io/reference/recipes/gemini_live_vision.md
- **AgentSession events:** https://docs.livekit.io/reference/agents/events.md

---

## Rollback

If the refactor fails and you need to revert:

```bash
git checkout refactor/bare-minimum  # back to the working branch
git branch -D refactor/agent-session-gemini  # delete the failed branch
```

The `refactor/bare-minimum` branch has the audio buffer fix committed
(`0e9649f`) and is the last known working state.
