# Refactoring Roadmap — Bare-Minimum to Full Product

**Branch:** `refactor/agent-session-gemini` (active)
**Last updated:** 2026-08-12

This guide tracks the incremental re-enablement of cut features, from the verified
bare-minimum base through to the full proposal architecture. Each step is independently
testable — do not proceed to the next step until the current one passes.

> **Architecture change (2026-08-12):** The custom `GeminiLiveSession` WebSocket
> plumbing has been replaced with LiveKit's `AgentSession` +
> `google.realtime.RealtimeModel` plugin. Audio, video, reconnection, VAD-based
> turn detection, and tool dispatch are now handled by the LiveKit framework
> instead of custom code. See `agent-session-refactor.md` for details. The
> re-enable steps below have been updated to reflect the new architecture.

---

## Current State

**Step 0 (bare-minimum) verified + AgentSession refactor applied.** 4 components
work end-to-end via LiveKit's `AgentSession` + `RealtimeModel`:

| Component   | Status | Role                                                                    |
| ----------- | ------ | ----------------------------------------------------------------------- |
| Gemini Live | ✅     | Realtime model (audio + video in, audio out, tool calls) via LiveKit    |
| InsightFace | ✅     | Face detection + 512-d embeddings (CPU, session recycle every 30 calls) |
| Neo4j       | ✅     | Person graph (search/get/register person)                               |
| Postgres    | ✅     | Face embedding persistence (survives restart)                           |

**Steps 1-5 completed:**

| Step | Status | What it does                                                              |
| ---- | ------ | ------------------------------------------------------------------------- |
| 1    | ✅     | Memory Pipeline — extraction → consolidation → Neo4j + Postgres           |
| 2    | ✅     | Semantic Retrieval — ContextEngine injects memories into system prompt    |
| 3    | ✅     | Scene Understanding — Gemini Vision analyzes frames → tool_ctx.last_scene |
| 4    | ✅     | Proactive Planner — context-aware reminders via 30s background loop       |
| 5    | ✅     | Observation Engine — 1s fusion + 30s TTL + speech + device telemetry      |

**Verification:** See `step0-verification.md` for the 10-step end-to-end test results
(original bare-minimum). See `agent-session-refactor.md` for the AgentSession
refactor details.

---

## Re-enable Steps

### Step 1: Memory Pipeline (extraction → consolidation)

**Goal:** Conversations become structured knowledge. "Asep suka sushi" → Neo4j
Person:Asep with LIKES→sushi edge + Postgres episodic record.

**Why first:** This is the core differentiator — the proposal's "Automatic Memory
Formation" (Core Feature #3). Without it, Memora is just a face recognizer + chatbot.

**What to wire:**

1. In `reasoning/agent/agent.py` (`MemoraAgent`):
   - Add `on_extract` callback to constructor
   - Override `on_user_turn_completed(self, turn_ctx, new_message)` — read the
     latest user message + agent response from `turn_ctx` and call
     `on_extract(text, session_id)`
   - The `AgentSession` fires `on_user_turn_completed` after VAD detects
     end-of-speech, before the agent's reply. This replaces the old
     `_on_turn()` / `turn_complete` callback pattern.

2. In `gateway/livekit/entrypoint.py`:
   - Lazily create a `ConversationSession` via `MemoryService().start_session()`
   - Set `tool_ctx.session_id` to the session UUID
   - Pass `on_extract=lambda text, sid: PipelineRunner().run(text, session_id=sid)`
     to `MemoraAgent`

3. The `PipelineRunner` already exists and works (`pipeline/runner.py`):
   - Filter → KnowledgeExtractor (Gemini structured output) → Consolidator → Neo4j + Postgres
   - No changes needed to the pipeline itself — just wire the trigger

**What NOT to wire yet:**

- ObservationEngine / WorkingMemory — skip for now, `tool_ctx.last_face` works fine
- TextEmbedder / TextIndex — skip, facts go to Postgres but aren't embeddable yet
- ContextEngine — skip, system prompt stays static (passed via `Agent(instructions=...)`)

**Test plan:**

1. Start worker, connect via dashboard/test script
2. Send prompt: "halo, nama saya Asep, saya suka sushi"
3. Wait for agent response (turn boundary triggers extraction)
4. Check Neo4j: `MATCH (p:Person {name:'Asep'})-[r:LIKES]->(x) RETURN x`
5. Check Postgres: `SELECT * FROM memory_facts WHERE content LIKE '%sushi%'`
6. Check Postgres: `SELECT * FROM conversation_messages WHERE content LIKE '%Asep%'`
7. Send prompt: "Asep kerja dimana?" — agent should answer via tool call to search_person

**Files to change:**

- `apps/backend/reasoning/agent/agent.py` — add `on_extract` param, wire `on_user_turn_completed`
- `apps/backend/gateway/livekit/entrypoint.py` — create session_id, pass on_extract callback

**Estimated diff:** ~30 lines

---

### Step 2: Semantic Memory Retrieval (ContextEngine + Retriever) ✅

**Goal:** Agent retrieves relevant memories at connect time and injects them into the
system prompt. "Siapa Asep?" → agent knows the answer without a tool call.

**Why second:** Depends on Step 1 — there needs to be data in the graph to retrieve.

**What was wired:**

1. In `gateway/livekit/entrypoint.py`:
   - Instantiate `TextEmbedder` (Gemini text embeddings)
   - Instantiate `TextMemoryIndex` (FAISS for text, 768-d)
   - Pass `text_embedder` + `text_index` to `PipelineRunner` → `Consolidator`
   - Instantiate `ContextEngine` with `Retriever(text_embedder=..., text_index=...)`
   - Pass `context_engine` to `MemoraAgent`

2. In `reasoning/agent/agent.py` (`MemoraAgent`):
   - Accept `context_engine` in constructor
   - In `on_enter()`, call `context_engine.build(current)` → context text
   - Call `self.update_instructions(build_system_instruction(text))` to inject
     the context package into the system prompt mid-session (no reconnect)

3. In `packages/shared/prompts/system.py`:
   - Added `{{context_package}}` placeholder back to `SYSTEM_INSTRUCTION`
   - Added first-person glasses perspective prompt

4. In `reasoning/prompts/system.py`:
   - Restored `build_system_instruction()` to replace `{{context_package}}` with context_text

5. In `pipeline/runner.py`:
   - Accept `text_embedder` + `text_index` params, pass to `Consolidator`

**Test results:** 390 tests pass, lint clean. Live verification pending.

**Files changed:**

- `apps/backend/gateway/livekit/entrypoint.py` — instantiate TextEmbedder + TextIndex + ContextEngine
- `apps/backend/reasoning/agent/agent.py` — accept context_engine, call update_instructions in on_enter
- `packages/shared/prompts/system.py` — add {{context_package}} placeholder + glasses prompt
- `apps/backend/reasoning/prompts/system.py` — restore replace logic
- `apps/backend/pipeline/runner.py` — pass-through text_embedder/text_index
- `apps/backend/tests/unit/test_reasoning.py` — 5 new tests + 1 updated

**Diff size:** ~50 lines production, ~50 lines test

---

### Step 3: Scene Understanding ✅

**Goal:** Agent knows where it is. "Dimana aku?" → "Anda di apotek."

**Why third:** The Gemini Vision memory leak from the old architecture is not present
in the new AgentSession architecture. Research confirmed: `google-genai` 2.17.0 has
the #2235 fix, image-understanding responses (small JSON) don't trigger #2369, and
client reuse is the correct pattern. No leak fix needed.

**What was wired:**

1. In `tools/registry.py`:
   - Added `last_scene: dict | None = None` to `ToolContext`

2. In `tools/observation/tools.py`:
   - `current_scene` reads from `ctx.last_scene` → returns location/objects/activity
   - `current_activity` reads from `ctx.last_scene` → returns activity/location

3. In `gateway/livekit/entrypoint.py`:
   - Instantiate `SceneUnderstander()`
   - Pass `scene_understander` to `handle_video_track()`

4. In `gateway/livekit/track_handler.py`:
   - Accept `scene_understander` param
   - Every 5 frames (~5s at 1 FPS): `_encode_jpeg(bgr)` → `scene_understander.understand(jpeg)` → `tool_ctx.last_scene`

**Test results:** 400 tests pass, lint clean. Live verification pending.

**Files changed:**

- `apps/backend/tools/registry.py` — added `last_scene` to `ToolContext`
- `apps/backend/tools/observation/tools.py` — `current_scene` + `current_activity` read from `last_scene`
- `apps/backend/gateway/livekit/entrypoint.py` — instantiate SceneUnderstander, pass to track_handler
- `apps/backend/gateway/livekit/track_handler.py` — call scene understander every 5 frames
- `apps/backend/tests/unit/test_tools.py` — 4 new tests for scene tools
- `apps/backend/tests/unit/test_gateway.py` — 3 new tests for _encode_jpeg + last_scene
- `apps/backend/tests/unit/test_reasoning.py` — 4 new Step 2 tests for context engine edge cases

**Diff size:** ~40 lines production, ~60 lines test

---

### Step 4: Proactive Planner ✅

**Goal:** Agent proactively reminds user about pending tasks when context matches.
Entering a pharmacy → "Jangan lupa beli paracetamol."

**Why fourth:** Depends on scene understanding (Step 3) for location context.

**What was wired:**

1. In `gateway/livekit/entrypoint.py`:
   - Instantiate `ProactivePlanner(reminder_service=..., shopping_service=...)`
   - Pass `planner` to `MemoraAgent`
   - Stop planner in `finally` block (not `on_exit` — single-agent, may never fire)

2. In `reasoning/agent/agent.py` (`MemoraAgent`):
   - Accept `planner` in constructor
   - In `on_enter()`, after greeting: `planner.start(self._get_context, self._on_proactive)`
   - `_get_context()` builds `CurrentContext` from `tool_ctx.last_face` + `tool_ctx.last_scene`
   - `_on_proactive(text)` calls `self.session.generate_reply(instructions=text)`

**Design decisions:**

- No `on_exit()` override — LiveKit `on_exit` is a workflow hook, not session-end.
  Cleanup in entrypoint `finally` block (reliable).
- No WorkingMemory/ObservationEngine — `_get_context()` reads from `tool_ctx`
  dicts directly (same pattern as Steps 1-3).
- No speech tracking — "Siapa ini?" trigger needs `current.speech`, which is
  always None without ObservationEngine. System prompt handles this instead.
  See `future-plans.md` for the plan to add speech tracking.

**Test results:** 342 tests pass, lint clean. Live verification pending.

**Files changed:**

- `apps/backend/reasoning/agent/agent.py` — `planner` param, `on_enter()` starts planner, `_get_context()`, `_on_proactive()`
- `apps/backend/gateway/livekit/entrypoint.py` — instantiate `ProactivePlanner`, pass to agent, stop in `finally`
- `apps/backend/tests/unit/test_reasoning.py` — 10 new tests in `TestProactivePlannerWiring`

**Diff size:** ~25 lines production, ~85 lines test

---

### Step 5: Observation Engine + Working Memory ✅

**Goal:** Restore the full perception fusion architecture from the PRD.

**Why last / optional:** The bare-minimum's direct dict approach (`tool_ctx.last_face`,
`tool_ctx.last_scene`) works well for a single-user demo. The ObservationEngine adds:

- 1s fusion window (dedup observations from multiple sources)
- 30s TTL on context (stale context expires)
- Single write path (no race conditions)
- Device telemetry processing (battery, button, wifi)
- Speech tracking via `user_input_transcribed` event

**What was wired:**

1. In `gateway/livekit/entrypoint.py`:
   - Instantiate `WorkingMemory` + `ObservationEngine(working_memory)`
   - Set `tool_ctx.working_memory = working_memory`
   - Start `obs_engine` after `AgentSession.start()`, stop in `finally`
   - Wire `user_input_transcribed` event → `SpeechObservation` (final only)
   - Wire device data channel topic → `handle_data_received` → `DeviceObservation`

2. In `gateway/livekit/track_handler.py`:
   - Accept `obs_engine` param
   - `_update_last_face` emits `FaceObservation` after writing to `tool_ctx.last_face`
   - Scene understanding emits `SceneObservation` after writing to `tool_ctx.last_scene`

3. In `tools/registry.py`:
   - Added `working_memory: Any = None` to `ToolContext`
   - `device_snapshot()` reads `DeviceObservation` from working_memory, falls back to `{}`

4. In `reasoning/agent/agent.py`:
   - `_get_context()` and `_build_context_text()` prefer `working_memory.get()`,
     fall back to `last_face`/`last_scene` dicts when working_memory is None or expired

**Design decisions:**

- Additive, not replacement — `last_face`/`last_scene` dicts stay, observation engine runs in parallel
- No speech suppression needed — `user_input_transcribed` is user-mic-only STT
- Final transcripts only — `is_final=False` (interim) transcripts are skipped

**Test results:** 353 tests pass, lint clean. Live verification pending.

**Files changed:**

- `apps/backend/gateway/livekit/entrypoint.py` — WorkingMemory + ObsEngine + speech + device wiring
- `apps/backend/gateway/livekit/track_handler.py` — emit FaceObservation + SceneObservation
- `apps/backend/tools/registry.py` — `working_memory` field + `device_snapshot()`
- `apps/backend/reasoning/agent/agent.py` — `_get_context()` + `_build_context_text()` prefer working_memory
- `apps/backend/tests/unit/test_gateway.py` — 3 new tests for FaceObservation emission
- `apps/backend/tests/unit/test_reasoning.py` — 5 new tests for working_memory preference
- `apps/backend/tests/unit/test_tools.py` — 3 new tests for device_snapshot from working_memory

**Diff size:** ~72 lines production, ~85 lines test

---

## Dependency Graph

```
Step 0 (verified)
  │
  ├── Step 1: Memory Pipeline
  │     │
  │     └── Step 2: Semantic Retrieval
  │           │
  │           └── Step 4: Proactive Planner (needs context from Step 2)
  │
  ├── Step 3: Scene Understanding (independent, needs leak fix)
  │     │
  │     └── Step 4: Proactive Planner (needs scene from Step 3)
  │
  └── Step 5: Observation Engine (optional, independent)
```

**Recommended order:** 1 → 2 → 3 → 4 → (5 optional)

Step 3 can run in parallel with Steps 1-2 since it's independent (different code path).

---

## Testing Approach

After each step, run the 10-step verification from `step0-verification.md` plus
the step-specific test plan. **Do not move to the next step if any test fails.**

The test script at `/tmp/opencode/test_face.py` can be reused — extend it with
step-specific assertions (e.g. check Neo4j for extracted facts after Step 1).

For quick smoke tests, use the dashboard at `http://localhost:3000`:

1. `cd apps/backend && uv run python -m workers.livekit_worker start`
2. `cd apps/dashboard && bun run dev`
3. Open `http://localhost:3000`, click Connect, test prompts

---

## Key Files Reference

| File                                                    | Role                                                 |
| ------------------------------------------------------- | ---------------------------------------------------- |
| `apps/backend/gateway/livekit/entrypoint.py`            | LiveKit job handler — AgentSession + RealtimeModel   |
| `apps/backend/gateway/livekit/track_handler.py`         | Video track → InsightFace face recognition loop      |
| `apps/backend/reasoning/agent/agent.py`                 | MemoraAgent — LiveKit Agent subclass with tools      |
| `apps/backend/tools/registry.py`                        | ToolContext — shared state injected into tool calls  |
| `apps/backend/perception/face/recognizer.py`            | FaceRecognizer — InsightFace adapter                 |
| `apps/backend/perception/scene/understander.py`         | SceneUnderstander — Gemini Vision adapter            |
| `apps/backend/perception/observation/engine.py`         | ObservationEngine — fusion window (bypassed)         |
| `apps/backend/perception/observation/working_memory.py` | WorkingMemory — TTL context (bypassed)               |
| `apps/backend/extraction/extractor.py`                  | KnowledgeExtractor — Gemini structured output        |
| `apps/backend/pipeline/runner.py`                       | PipelineRunner — filter→extract→consolidate          |
| `apps/backend/pipeline/consolidator.py`                 | Consolidator — write to Neo4j + Postgres             |
| `apps/backend/context/engine.py`                        | ContextEngine — retrieval→ranking→packaging          |
| `apps/backend/reasoning/planner/planner.py`             | ProactivePlanner — context-aware reminders           |
| `apps/backend/reasoning/response/display.py`            | Display — model text → glasses OLED via data channel |
| `packages/config/env/settings.py`                       | Settings — all env config (single source of truth)   |

**Deleted in AgentSession refactor:**

| File (deleted)                                   | Replaced by                                     |
| ------------------------------------------------ | ----------------------------------------------- |
| `apps/backend/reasoning/session/live_session.py` | `livekit.plugins.google.realtime.RealtimeModel` |
| `apps/backend/reasoning/tools/router.py`         | `@function_tool` decorator on `MemoraAgent`     |
| `apps/backend/reasoning/response/speaker.py`     | `AgentSession` automatic audio output           |
| `apps/backend/perception/speech/forwarder.py`    | `AgentSession` automatic audio input            |
| `apps/backend/gateway/session.py`                | Inlined into `entrypoint.py`                    |

---

## What the Full Product Looks Like (after all steps)

```
Video frame
  → FrameSampler (0.5 FPS)
  → FaceRecognizer → FaceRepository.lookup → tool_ctx.last_face
  → SceneUnderstander → tool_ctx.last_scene          (Step 3)

Audio + Video
  → LiveKit → AgentSession → Gemini RealtimeModel (audio + video, direct)
  → VAD-based turn detection (built-in)

Prompt (data channel)
  → entrypoint data_received → session.generate_reply()

Gemini RealtimeModel (via AgentSession)
  → tool_call → @function_tool methods on MemoraAgent
    → reads tool_ctx (last_face, last_scene, services)
  → audio output → LiveKit audio track (automatic)
  → transcription → conversation_item_added event → Display (OLED)

Turn boundary (on_user_turn_completed)
  → PipelineRunner.run(text, session_id)              (Step 1)
    → KnowledgeExtractor (Gemini structured output)
    → Consolidator → Neo4j (graph) + Postgres (episodic + facts)

Agent enter (on_enter)
  → ContextEngine.build() → context_text              (Step 2)
    → Retriever (Neo4j + Postgres + TextIndex)
    → Ranker
    → Summarizer (Gemini)
  → session.update_instructions(system prompt with context package)

Proactive loop (every 30s)                              (Step 4)
  → ProactivePlanner.check_context()
  → if reminder matches scene → session.generate_reply("Jangan lupa...")
```

This matches the proposal's Appendix A.10 end-to-end workflow.
