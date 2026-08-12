# Bare-Minimum Refactor

**Branch:** `refactor/bare-minimum`
**Base:** `feat/aldo`
**Date:** 2026-08-11
**Result:** 411 tests pass, lint clean, -464 net lines (695 deleted, 231 added)

---

## Problem

After 7+ hours of debugging, the system had ~10 async components each failing
independently and non-deterministically. Every fix revealed another layer of
breakage. The core flow — user speaks, agent responds, face recognized — never
worked end-to-end.

### Issues encountered (chronological)

| #   | Symptom                            | Root cause                                                                           |
| --- | ---------------------------------- | ------------------------------------------------------------------------------------ |
| 1   | Worker gets no job dispatch        | `LiveKitAPI` constructor used wrong key name (`apiSecret` vs `secret`)               |
| 2   | Face not recognized after restart  | `register_face` Postgres save silently swallowed (`log.warning` not `log.exception`) |
| 3   | Face score=0.000 during session    | FAISS index empty (0 embeddings from DB), agent never called `register_face`         |
| 4   | Memory leak 274MB to 1.3GB in 3min | Scene understander calling Gemini Vision every 2s                                    |
| 5   | Memory leak 242MB to 1.4GB in 30s  | `np.frombuffer` view kept LiveKit internal buffer alive                              |
| 6   | Agent confusion after reconnect    | Gemini Live 1011 errors lose conversation context                                    |
| 7   | Reasoning traces on OLED display   | `model_turn` text parts sent to display instead of only `output_transcription`       |
| 8   | Agent not responding               | `connect()` blocked `agent.start()` in infinite retry loop                           |
| 9   | Agent still not responding         | Gemini Live connect fails, receive loop never starts                                 |
| 10  | Face score=0.000 every frame       | FAISS index empty, no embeddings persisted                                           |
| 11  | Memory still growing               | InsightFace ONNX runtime or LiveKit VideoStream buffer accumulation                  |
| 12  | Cross-talk between developers      | Same `agent_name` on shared LiveKit Cloud account                                    |

**Pattern:** every fix revealed another nondeterministic failure in a component
we didn't need for the core demo flow.

---

## Decision

Strip the system to 4 components that are individually testable and
deterministic. Bypass (not delete) the remaining components so they can be
re-enabled incrementally once the core flow is stable.

### What stays (4 components)

| Component       | Role                                                            | Why it stays                      |
| --------------- | --------------------------------------------------------------- | --------------------------------- |
| **Gemini Live** | Conversation, tool calls, audio output                          | The brain — no alternative        |
| **InsightFace** | Face detection + 512-d embeddings                               | Gemini can't match a face gallery |
| **Neo4j**       | Person graph (`search_person`, `get_person`, `register_person`) | Identity persistence              |
| **Postgres**    | Face embedding persistence                                      | Survives restarts                 |

### What's bypassed (7 components)

| Component                       | What it did                                                 | Why bypass                                                | How to re-enable                                           |
| ------------------------------- | ----------------------------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------- |
| **ObservationEngine**           | Fused observations into `CurrentContext` via 1s async queue | Fusion window timing caused face observations to get lost | Re-wire `emit()` call in video loop                        |
| **WorkingMemory**               | Held `CurrentContext` with 30s TTL                          | Tool context read from this, but always stale or empty    | Re-wire `working_memory.get()` in tool context             |
| **ContextEngine**               | Built context package for system prompt via Retriever       | Needed TextEmbedder + TextIndex — another failure layer   | Pass dynamic string as `context_text` to `connect()`       |
| **ProactivePlanner**            | Periodic reminder checker                                   | Background task, another failure mode                     | Call `planner.start()` in `agent.start()`                  |
| **SceneUnderstander**           | Gemini Vision scene analysis                                | Memory leak (~100MB/min), already disabled                | Don't instantiate in `RoomSession.create()` (already done) |
| **TextEmbedder + TextIndex**    | Semantic memory retrieval                                   | ~200MB memory, model load time, another FAISS index       | Instantiate in `RoomSession.create()`                      |
| **Consolidator/PipelineRunner** | Extracted facts from conversation                           | Ran on turn boundary, needed MemoryService + DB           | Wire `on_extract` callback in `ReasoningAgent`             |

---

## Architecture: Before vs After

### Before (~10 async components)

```
Video frame
  -> FrameSampler
  -> FaceRecognizer
  -> FaceObservation
  -> ObservationEngine.emit()     # async queue
  -> fuse()                       # 1s fusion window
  -> WorkingMemory.set()
  -> session.sync_context()
  -> ToolContext.current_context

Prompt
  -> entrypoint
  -> agent.feed_prompt()
  -> live_session.send_text()
  -> Gemini Live
  -> tool_call
  -> dispatch
  -> ToolContext reads current_context
  -> WorkingMemory.get()
  -> CurrentContext.observations   # embedding buried in observations list
  -> tool result

Turn boundary
  -> on_extract
  -> PipelineRunner
  -> Consolidator
  -> MemoryService
  -> Postgres + TextIndex

Agent start
  -> ContextEngine.build()        # needs Retriever
  -> Retriever                    # needs TextEmbedder + TextIndex
  -> build system prompt with context package
  -> Gemini Live connect()        # blocking retry loop
  -> (blocked forever if connect fails)
```

### After (4 components)

```
Video frame
  -> FrameSampler
  -> FaceRecognizer
  -> face_repo.lookup()
  -> tool_ctx.last_face = {embedding, person_id, name, score, is_known}  # direct dict

Prompt
  -> entrypoint
  -> agent.feed_prompt()
  -> live_session.send_text()
  -> Gemini Live
  -> tool_call
  -> dispatch
  -> tool_ctx.last_face            # direct read
  -> tool result

Agent start
  -> Gemini Live connect()         # non-blocking background task
  -> (prompts queue during connect, flush on success)
```

---

## File-by-file changes

### `apps/backend/tools/registry.py` — ToolContext

**Before:** `current_context: Any = None` (a `CurrentContext` object from
WorkingMemory). `current_face_embedding()` iterated `current_context.observations`
to find an embedding. `device_snapshot()` iterated observations for
`DeviceObservation`.

**After:** `last_face: dict | None = None` — a plain dict written directly by
the video loop:

```python
{
    "embedding": np.ndarray,
    "person_id": str | None,
    "name": str | None,
    "score": float,
    "is_known": bool,
    "is_possible": bool,
}
```

`current_face_embedding()` reads `last_face["embedding"]` directly.
`device_snapshot()` returns `{}` (no device telemetry in bare-minimum).

### `apps/backend/gateway/livekit/track_handler.py` — Video loop

**Before:** `_lookup_face()` returned a `FaceObservation` which was emitted to
`ObservationEngine.emit()`. The observation engine fused it into
`CurrentContext` via a 1s window. `session.sync_context()` pushed the
`CurrentContext` to `ToolContext.current_context`.

**After:** `_update_last_face()` writes the face result directly to
`session.tool_ctx.last_face`. No observation engine, no working memory, no
fusion window, no `sync_context()`.

### `apps/backend/tools/observation/tools.py` — Observation tools

**Before:** `current_scene`, `visible_people`, `current_activity` read from
`ctx.current_context` (a `CurrentContext` object).

**After:** `visible_people` reads from `ctx.last_face` directly. `current_scene`
and `current_activity` return `{"available": False}` (no scene understander).

### `apps/backend/gateway/session.py` — RoomSession

**Before:** `RoomSession.create()` instantiated `WorkingMemory`,
`ObservationEngine`, `SceneUnderstander`, `TextEmbedder`, `TextMemoryIndex`,
`ProactivePlanner`, and wired an `on_extract` hook to `PipelineRunner`. The
session held 9 fields.

**After:** `RoomSession.create()` instantiates only `FaceRepository` (from
Postgres) and `ReasoningAgent`. The session holds 4 fields: `tool_ctx`,
`agent`, `face_repo`, `tasks`. `start()` calls `agent.start(current=None)`.
`stop()` cancels tasks + stops agent.

### `apps/backend/reasoning/agent/agent.py` — ReasoningAgent

**Before:** Constructor took `engine` (ContextEngine), `on_extract`,
`emit_observation`, `planner`, `text_embedder`, `text_index`. `start()` called
`engine.build(current)` to generate a context package, then passed it to
`session.connect(context_text=...)`. Wired `_on_turn` to trigger extraction.
Wired `_on_transcription` to emit `SpeechObservation` to the observation engine.

**After:** Constructor takes only `room`, `tool_ctx`, `session`, `speaker`,
`display`. `start()` passes `context_text=""` (static system prompt).
`_on_turn()` is a no-op. `_on_transcription()` just logs.

### `packages/shared/prompts/system.py` — System prompt

**Before:** `SYSTEM_INSTRUCTION` ended with `Konteks saat ini (diperbarui via
alat): {{context_package}}`. The `build_system_instruction()` function replaced
this placeholder with context text at connect time.

**After:** `SYSTEM_INSTRUCTION` ends with `Konteks saat ini diperbarui via alat
(visible_people, current_scene, dll.). Panggil alat tersebut untuk mendapatkan
informasi terkini.` No placeholder. `build_system_instruction()` returns the
static text unchanged.

### `apps/backend/reasoning/prompts/system.py` — Prompt builder

**Before:** `build_system_instruction(context_text)` did
`SYSTEM_INSTRUCTION.replace("{{context_package}}", context_text)`.

**After:** `build_system_instruction(context_text)` returns `SYSTEM_INSTRUCTION`
unchanged. `context_text` is accepted for API compatibility but ignored.

### `apps/backend/gateway/livekit/entrypoint.py` — Entrypoint

**Before:** `data_received` for non-prompt topics called
`handle_data_received(data, topic, session.observation_engine)` to emit
`DeviceObservation` into the observation engine.

**After:** `data_received` for "device" topic just logs it. No observation
engine to emit to. `handle_data_received` import removed.

---

## What we lose (temporarily)

| Feature                                    | Re-enable path                                                                                     |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| Episodic memory (conversation persistence) | Wire `on_extract` -> `PipelineRunner` in `ReasoningAgent`                                          |
| Semantic memory retrieval                  | Instantiate `TextEmbedder` + `TextIndex` in `RoomSession.create()`                                 |
| Proactive reminders                        | Pass `planner` to `ReasoningAgent`, call `planner.start()`                                         |
| Scene understanding                        | Instantiate `SceneUnderstander` (fix memory leak first)                                            |
| Observation fusion                         | Wire `ObservationEngine` -> `WorkingMemory` in `RoomSession.create()`                              |
| Device telemetry                           | Wire `data_channel.handle_data_received` -> observation engine                                     |
| Context package in system prompt           | Add `{{context_package}}` back to `SYSTEM_INSTRUCTION`, pass dynamic `context_text` to `connect()` |

---

## Verification plan

Test in this order — each step is verifiable in isolation:

1. **Worker registers** -> check `registered worker` log
2. **Dashboard connects** -> check `[token] agent dispatch created` in dashboard console
3. **Job dispatched** -> check `received job request` in worker log
4. **Gemini Live connects** -> check `gemini live connected` log
5. **Prompt "halo"** -> agent responds with audio + display text
6. **Face detected** -> check `frame: 1280x720 faces=1` log
7. **Prompt "ini siapa"** -> agent calls `search_person_by_face` -> returns unknown
8. **Prompt "ini aldo"** -> agent calls `search_person` -> auto-registers face -> persists to Postgres
9. **Restart worker** -> check `from_db: loaded 1 face embedding(s)`
10. **Face recognized** -> check `face lookup: <person_id> name=aldo score=0.XX known=True`

If a step fails, there are only 4 components to check — not 10.
