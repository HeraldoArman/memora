# AgentSession + Gemini RealtimeModel Refactor

**Branch:** `refactor/agent-session-gemini`
**Base:** `refactor/bare-minimum`
**Date:** 2026-08-12

---

## Problem

The custom `GeminiLiveSession` plumbing caused multiple issues:

1. **Audio race condition:** The `SpeechForwarder` started consuming mic frames
   before Gemini connected. Every chunk was silently dropped (`_session is None`
   → `return`). Audio buffering was added but made things worse — stale audio
   flooded Gemini on reconnect.

2. **Reconnect feedback loop:** `_recent_turns` re-injection caused the model to
   respond to its own old text after every reconnect → new turn → re-injected
   again → infinite loop. The model never processed live audio.

3. **No video to Gemini:** The camera feed went to InsightFace only. Gemini never
   saw video — it could only identify faces via tool calls, not see the scene.

4. **Fragile plumbing:** ~900 lines of custom WebSocket management, audio
   forwarding, reconnection logic, and tool dispatch — all of which LiveKit's
   framework handles natively.

---

## Solution

Replace the entire custom plumbing with LiveKit's `AgentSession` +
`google.realtime.RealtimeModel` plugin. The framework handles:

- Audio/video streaming to Gemini (via `RoomOptions(video_input=True)`)
- WebSocket lifecycle, reconnection, VAD-based turn detection
- Tool calling (via `@function_tool` decorator on `Agent` subclass)
- Audio output (speaker track published automatically)
- Transcription (published to room automatically)

---

## Architecture: Before vs After

### Before (custom plumbing, ~900 lines)

```
mic → SpeechForwarder → _AudioShim → GeminiLiveSession.send_audio → Gemini WS
camera → FrameSampler → InsightFace → tool_ctx.last_face (tool only)
text prompt → data_received → agent.feed_prompt → GeminiLiveSession.send_text
Gemini WS → receive_loop → on_text → Display → data channel "display"
Gemini WS → receive_loop → audio blob → Speaker → AudioSource → room
Gemini WS → receive_loop → tool_call → router → send_tool_response
extraction → on_turn_complete → PipelineRunner
```

### After (AgentSession + RealtimeModel, ~200 lines)

```
mic → LiveKit → AgentSession → Gemini RealtimeModel (audio, direct)
camera → LiveKit → AgentSession → Gemini RealtimeModel (video, direct, 1 FPS)
                                          ↕
                     Gemini sees + hears everything live
                                          ↕
text prompt → data_received → session.generate_reply()
Gemini → AgentSession → audio output (automatic, speaker track)
Gemini → AgentSession → transcription (automatic, conversation_item_added)
Gemini → AgentSession → tool_call → @function_tool methods on MemoraAgent
extraction → on_user_turn_completed hook → PipelineRunner
display → conversation_item_added event → Display → data channel "display"
```

### Key architectural changes

| Concern            | Before                                                     | After                                              |
| ------------------ | ---------------------------------------------------------- | -------------------------------------------------- |
| Audio to Gemini    | `SpeechForwarder` → `_AudioShim` → `send_audio()`          | `AgentSession` (automatic)                         |
| Video to Gemini    | Never sent (InsightFace only)                              | `RoomOptions(video_input=True)` (automatic, 1 FPS) |
| Audio from Gemini  | `receive_loop` → `Speaker.feed()` → `AudioSource`          | `AgentSession` (automatic)                         |
| Tool dispatch      | `ToolRouter.dispatch_tool_call()` → `send_tool_response()` | `@function_tool` decorator                         |
| Reconnection       | Custom backoff + `_recent_turns` re-injection              | `RealtimeModel` plugin (internal)                  |
| Turn detection     | `turn_complete` / `generation_complete` events             | VAD-based (built into RealtimeModel)               |
| Display (OLED)     | `output_transcription` → `on_text` callback                | `conversation_item_added` event                    |
| Text prompts       | `agent.feed_prompt()` → `send_text()`                      | `session.generate_reply()`                         |
| System prompt      | `build_system_instruction()` at connect                    | `Agent(instructions=...)`                          |
| Extraction trigger | `_on_turn()` at turn boundary                              | `on_user_turn_completed()` hook                    |

---

## File-by-file changes

### New: `reasoning/agent/agent.py` (rewritten)

**Before:** `ReasoningAgent` class with custom `start()`, `stop()`, `feed_prompt()`,
`feed_audio()`, `_on_turn()`, `_on_transcription()`.

**After:** `MemoraAgent(Agent)` — LiveKit `Agent` subclass with:

- `instructions=SYSTEM_INSTRUCTION` in constructor
- `@function_tool` methods for all tools (visible_people, search_person, etc.)
- `on_enter()` for greeting
- `on_user_turn_completed()` for extraction trigger
- `conversation_item_added` event listener for Display (OLED)

### Rewritten: `gateway/livekit/entrypoint.py`

**Before:** Manual track subscription, `RoomSession.create()`, `session.start()`,
custom `data_received` handler, `track_subscribed` handler for audio + video.

**After:** `AgentSession` + `RealtimeModel` + `RoomOptions(video_input=True)`.
Track handler kept for InsightFace video loop only. Data handler for "prompt"
topic calls `session.generate_reply()`.

### Simplified: `gateway/livekit/track_handler.py`

**Before:** `handle_video_track()` (InsightFace) + `handle_audio_track()`
(SpeechForwarder → _AudioShim → agent.feed_audio).

**After:** `handle_video_track()` only. `handle_audio_track()` and `_AudioShim`
deleted — AgentSession handles audio.

### Kept: `reasoning/response/display.py`

No changes. Still publishes text to "display" topic via data channel. Called
from the `conversation_item_added` event handler instead of `on_text` callback.

### Deleted files

| File                                | Lines | Replaced by                                     |
| ----------------------------------- | ----- | ----------------------------------------------- |
| `reasoning/session/live_session.py` | ~660  | `livekit.plugins.google.realtime.RealtimeModel` |
| `reasoning/tools/router.py`         | ~90   | `@function_tool` decorator on `MemoraAgent`     |
| `reasoning/response/speaker.py`     | ~100  | `AgentSession` automatic audio output           |
| `perception/speech/forwarder.py`    | ~60   | `AgentSession` automatic audio input            |
| `gateway/session.py`                | ~130  | Inlined into `entrypoint.py`                    |

**~1,040 lines deleted, ~200 lines of new code.**

---

## What stays the same

- `Display` class (OLED data channel publishing)
- InsightFace face recognition pipeline (`recognizer.py`, `sampler.py`)
- Tool implementations (`tools/person/tools.py`, `tools/memory/tools.py`, etc.)
  — only the dispatch mechanism changes from registry+router to `@function_tool`
- `ToolContext` dataclass
- Pipeline runner (extraction)
- Store init (`_init_stores`)
- Dashboard code (no changes needed)
- System prompt (`prompts/system.py`)
- All tests for tools, pipeline, extraction, services

---

## Dependencies

### New dependency

```
livekit-agents[google]  # adds livekit.plugins.google with RealtimeModel
```

Already installed: `livekit==1.1.14`, `livekit-agents==1.6.9`. The `[google]`
extra adds the `livekit.plugins.google` module.

### Dashboard compatibility

No dashboard changes needed. The data channel protocol is unchanged:

- `prompt` topic: dashboard → agent (text prompts)
- `display` topic: agent → dashboard (OLED text)
- `device` topic: dashboard → agent (telemetry, logged only)

---

## Risks & mitigations

| Risk                                                   | Mitigation                                                    |
| ------------------------------------------------------ | ------------------------------------------------------------- |
| `livekit-agents[google]` incompatible with Python 3.14 | Check before installing; pin to 3.12 if needed                |
| Gemini native audio model still drops connection       | `RealtimeModel` plugin handles reconnection internally        |
| Display data channel format changes                    | Keep `Display` class as-is, wire from event listener          |
| InsightFace + Gemini both consuming same video track   | LiveKit handles track fan-out natively                        |
| Tool context needs to be on the Agent                  | Pass via constructor, store as instance state                 |
| Dashboard prompt topic needs handling                  | Keep `data_received` handler, call `session.generate_reply()` |

---

## Verification plan

1. `uv sync` — install `livekit-agents[google]`
2. `uv run pytest tests/ -x` — all existing tests pass
3. `bun run dev` — start dashboard + backend + worker
4. Open `http://localhost:3000`, connect
5. Speak — agent should hear and respond (audio + display)
6. Send "halo" prompt — agent responds
7. Send "ini siapa" prompt — agent calls `visible_people` tool
8. Point camera at face — InsightFace recognizes, agent identifies
9. Verify no reconnect loops in logs
10. Verify `input_transcription` events in logs (audio reaching Gemini)
