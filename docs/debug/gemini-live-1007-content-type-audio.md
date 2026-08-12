# Gemini Live 1007: "The audio content type (CONTENT_TYPE_AUDIO) is not supported for this model configuration"

- **Date:** 2026-08-12
- **Service:** `backend-worker` (LiveKit agent worker)
- **Status:** RESOLVED (2026-08-12). Root cause: LLM on AgentSession instead of Agent.
- **Branch:** `develop`

## TL;DR

The agent connected to Gemini Live, received the greeting, but crashed with
`1007 None. The audio content type (CONTENT_TYPE_AUDIO) is not supported for
this model configuration` as soon as the user spoke their first word. The
LiveKit plugin misinterprets all 1007 errors as "context exhausted" and
terminates the session.

Root cause: `google.realtime.RealtimeModel` was passed to `AgentSession(llm=...)`
instead of `Agent(llm=...)`. Moving the LLM to the Agent (matching the
LiveKit vision recipe and tuntun-in reference implementation) fixed it.

## Timeline

1. Initial config had `context_window_compression` + `media_resolution=MEDIUM`
   on `AgentSession(llm=...)` with `text_output` in RoomOptions.
2. First 1007: `context_window_compression` is unsupported on
   `gemini-2.5-flash-native-audio-preview-12-2025` — rejected at connect time.
   Removed it.
3. Second 1007: `media_resolution=MEDIUM` causes the model to reject audio
   after receiving video frames. Removed it.
4. Third 1007: `text_output=TextOutputOptions(sync_transcription=False)` in
   RoomOptions was replaced with `audio_output=True` — still crashed.
5. Fourth 1007: Added aggressive VAD tuning (`realtime_input_config`) — still
   crashed.
6. Fifth attempt: Moved `RealtimeModel` from `AgentSession(llm=...)` to
   `Agent(llm=...)` (matching tuntun-in). **This fixed the 1007.**
7. `output_audio_transcription=None` was tried to fix audio output but broke
   it — reverted. The minimal config (`model`, `voice`, `api_key` only) works.

## Root cause

The LiveKit `AgentSession` constructs the realtime session differently when
the LLM is passed to it directly vs when the LLM is on the `Agent`. When the
LLM is on `AgentSession`, the session config path produces a
`LiveConnectConfig` that the native audio model rejects after receiving the
first audio chunk. The exact mechanism is internal to
`livekit.agents.voice.agent_activity` — the session may set extra config fields
(like `history_config` or `session_resumption`) that the native audio model
doesn't support alongside video input.

When the LLM is on the `Agent`, the `AgentSession` discovers it via the agent's
`llm` property and the config path matches the documented vision recipe.

## Key references

- **LiveKit vision recipe** (`docs/refactoring/livekit-docs/gemini-vision-recipe.md`):
  Shows `Agent(llm=google.beta.realtime.RealtimeModel(...))` then
  `session.start(agent=Assistant())` — LLM on the Agent, not the session.
- **Tuntun-in reference** (`/home/pongo/projects/garudahacks/tuntun-in/apps/agent/src/tuntun_agent/agent.py`):
  Same pattern — `super().__init__(instructions=..., llm=llm)`.
- **Google forum** (https://discuss.ai.google.dev/t/received-1007-invalid-payload-using-gemini-live-api/83206/13):
  `response_modalities=["AUDIO", "TEXT"]` causes 1007 on native audio models.
  Use `["AUDIO"]` only + `output_audio_transcription` for text.
- **js-genai issue #1189** (https://github.com/googleapis/js-genai/issues/1189):
  Known bug — 1007 after sending first microphone audio chunk with
  `gemini-2.5-flash-native-audio-preview-12-2025`.
- **livekit/agents issue #5260** (https://github.com/livekit/agents/issues/5260):
  `generate_reply` times out with 1007 on Gemini 3.1 — similar config rejection.

## What was tried and discarded

| Change                                                                            | Result                      | Why                                                             |
| --------------------------------------------------------------------------------- | --------------------------- | --------------------------------------------------------------- |
| `context_window_compression=ContextWindowCompressionConfig(trigger_tokens=20000)` | 1007 at connect             | Unsupported on native audio preview model                       |
| `media_resolution=MEDIA_RESOLUTION_MEDIUM`                                        | 1007 after first audio      | Model rejects audio with this config when video is active       |
| `text_output=TextOutputOptions(sync_transcription=False)` in RoomOptions          | 1007 after first audio      | TranscriptSynchronizer may alter response modality expectations |
| `audio_output=True` in RoomOptions (replacing text_output)                        | 1007 after first audio      | Not the cause — but needed for audio to reach the room          |
| `output_audio_transcription=None`                                                 | No 1007 but no audio output | Disabling transcription breaks the audio output path            |
| `realtime_input_config` with aggressive VAD                                       | 1007 after first audio      | VAD tuning doesn't affect the config rejection                  |
| `gemini-live-2.5-flash-native-audio` (stable alias)                               | ValueError at init          | VertexAI-only model; requires `vertexai=True`                   |
| **LLM on Agent, not AgentSession**                                                | **Works**                   | Correct config path for native audio + video                    |
| Minimal RealtimeModel config (`model`, `voice`, `api_key` only)                   | Works                       | No unsupported options in the config                            |

## The fix

### Before (broken)

```python
# entrypoint.py
session = AgentSession(
    llm=google.realtime.RealtimeModel(
        model=settings.gemini_live_model,
        voice="Puck",
        media_resolution=gtypes.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
        context_window_compression=gtypes.ContextWindowCompressionConfig(
            trigger_tokens=20000,
        ),
    ),
)
agent = MemoraAgent(tool_ctx=tool_ctx, ...)  # no llm kwarg
await session.start(room=room, agent=agent, ...)
```

### After (working)

```python
# agent.py — MemoraAgent.__init__
super().__init__(instructions=SYSTEM_INSTRUCTION, llm=llm)

# entrypoint.py — LLM is on the Agent, session is bare
agent = MemoraAgent(tool_ctx=tool_ctx, ...)
session = AgentSession()
await session.start(
    room=room,
    agent=agent,
    room_options=room_io.RoomOptions(
        video_input=True,
        audio_input=True,
        audio_output=True,
    ),
)
```

## Files changed

- `apps/backend/reasoning/agent/agent.py` — Added `llm` kwarg to `MemoraAgent.__init__`,
  passed to `super().__init__(instructions=..., llm=llm)`. Default LLM is
  `google.realtime.RealtimeModel(model=..., voice="Puck", api_key=...)` with
  no extra options.
- `apps/backend/gateway/livekit/entrypoint.py` — Removed LLM from `AgentSession()`,
  removed `context_window_compression`, `media_resolution`, `text_output`.
  Added `audio_output=True` to RoomOptions.
- `packages/config/env/settings.py` — Default `gemini_live_model` reverted to
  `gemini-2.5-flash-native-audio-preview-12-2025`.
- `apps/backend/tests/unit/test_env_settings.py` — Updated default assertion.

## Lessons

1. **Follow the documented recipe.** The LiveKit vision recipe puts the LLM on
   the Agent, not the session. This is not a style choice — it changes the
   internal config path.
2. **The plugin's 1007 error message is misleading.** It always says "context
   exhausted" but the actual reason is in the websocket close payload
   (`The audio content type (CONTENT_TYPE_AUDIO) is not supported for this
model configuration`). Read the full error, not the plugin's interpretation.
3. **Native audio models are picky about config.** `context_window_compression`,
   `media_resolution`, and `response_modalities=["AUDIO", "TEXT"]` are all
   rejected. Use the minimal config that works.
4. **`output_audio_transcription` must not be None** — it's needed for the
   audio output path. The plugin defaults it to `AudioTranscriptionConfig()`
   which is correct.
5. **`gemini-live-2.5-flash-native-audio` is VertexAI-only.** The Gemini API
   model name is `gemini-2.5-flash-native-audio-preview-12-2025`.
