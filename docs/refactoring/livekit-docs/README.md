# LiveKit Docs Reference — Saved for AgentSession Refactor

**Fetched:** 2026-08-12
**Purpose:** Offline reference for the `refactor/agent-session-gemini` branch.
These are snapshots of the LiveKit + Gemini docs at the time of the refactor.

## Index

| File                      | Source URL                                                       | What it covers                                                                                                                          |
| ------------------------- | ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `gemini-plugin.md`        | https://docs.livekit.io/agents/models/realtime/plugins/gemini.md | Gemini Live API plugin: RealtimeModel config, video input, turn detection, thinking, separate TTS                                       |
| `agent-sessions.md`       | https://docs.livekit.io/agents/logic/sessions.md                 | AgentSession orchestrator: lifecycle, events, options, video sampling, user away timeout                                                |
| `function-tools.md`       | https://docs.livekit.io/agents/logic/tools/definition.md         | @function_tool decorator, RunContext, tool flags, structured output, dynamic tools                                                      |
| `video-input.md`          | https://docs.livekit.io/agents/multimodality/vision/video.md     | Live video input via RoomOptions(video_input=True), frame sampling, video frame encoding                                                |
| `nodes-hooks.md`          | https://docs.livekit.io/agents/build/nodes.md                    | Pipeline nodes: on_enter, on_exit, on_user_turn_completed, stt_node, llm_node, tts_node, realtime_audio_output_node, transcription_node |
| `gemini-vision-recipe.md` | https://docs.livekit.io/reference/recipes/gemini_live_vision.md  | Complete minimal example: Gemini Realtime + live vision + proactivity                                                                   |
| `tools-overview.md`       | https://docs.livekit.io/agents/logic/tools.md                    | Tool types (function vs provider), toolsets, async tools, MCP                                                                           |
| `audio-overview.md`       | https://docs.livekit.io/agents/multimodality/audio.md            | Agent speech, instant connect, preemptive generation, initiating speech                                                                 |
| `agents-handoffs.md`      | https://docs.livekit.io/agents/logic/agents-handoffs.md          | Agent definition, on_enter/on_exit, handoffs, tool handoffs, context preservation                                                       |
| `text-transcriptions.md`  | https://docs.livekit.io/agents/multimodality/text.md             | Transcription output, sync vs async, TTS-aligned transcripts, text streams                                                              |
| `gemini-live-api.md`      | https://ai.google.dev/gemini-api/docs/live                       | Google's Gemini Live API docs: streaming, audio, video, tools, system instructions                                                      |
| `agent-events.md`         | https://docs.livekit.io/reference/agents/events.md               | Event reference: agent_state_changed, user_input_transcribed, conversation_item_added, close                                            |
| `turn-detection.md`       | https://docs.livekit.io/agents/logic/turns.md                    | Turn detection modes, VAD, interruptions, user turn limits                                                                              |
| `voice-ai-quickstart.md`  | https://docs.livekit.io/agents/start/voice-ai.md                 | Quickstart: STT-LLM-TTS pipeline vs realtime models, starter projects                                                                   |

## Most important for this refactor

1. **`gemini-vision-recipe.md`** — the minimal working example of exactly what we're building
2. **`gemini-plugin.md`** — RealtimeModel config parameters (model, voice, proactivity, video_input)
3. **`function-tools.md`** — how to convert our existing tools to @function_tool methods
4. **`nodes-hooks.md`** — on_enter, on_user_turn_completed (replaces our _on_turn callback)
5. **`agent-events.md`** — conversation_item_added event (replaces output_transcription → Display)
6. **`agent-sessions.md`** — AgentSession lifecycle, RoomOptions, video sampling config
