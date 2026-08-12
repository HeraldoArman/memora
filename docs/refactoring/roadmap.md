# Refactoring Roadmap — Bare-Minimum to Full Product

**Branch:** `refactor/bare-minimum`
**Last updated:** 2026-08-11

This guide tracks the incremental re-enablement of cut features, from the verified
bare-minimum base through to the full proposal architecture. Each step is independently
testable — do not proceed to the next step until the current one passes.

---

## Current State

**Step 0 (bare-minimum) is verified.** 4 components work end-to-end:

| Component   | Status | Role                                                                    |
| ----------- | ------ | ----------------------------------------------------------------------- |
| Gemini Live | ✅     | Conversation, tool calls, audio out, OLED display                       |
| InsightFace | ✅     | Face detection + 512-d embeddings (CPU, session recycle every 30 calls) |
| Neo4j       | ✅     | Person graph (search/get/register person)                               |
| Postgres    | ✅     | Face embedding persistence (survives restart)                           |

**Verification:** See `step0-verification.md` for the 10-step end-to-end test results.

---

## Re-enable Steps

### Step 1: Memory Pipeline (extraction → consolidation)

**Goal:** Conversations become structured knowledge. "Asep suka sushi" → Neo4j
Person:Asep with LIKES→sushi edge + Postgres episodic record.

**Why first:** This is the core differentiator — the proposal's "Automatic Memory
Formation" (Core Feature #3). Without it, Memora is just a face recognizer + chatbot.

**What to wire:**

1. In `reasoning/agent/agent.py`:
   - Add `on_extract` callback to constructor
   - In `_on_turn()`, read the recent conversation turns from `session._recent_turns`
     and call `on_extract(text, session_id)`
   - Don't wait for ObservationEngine — use the turns already captured in
     `GeminiLiveSession._recent_turns` (simpler, no new dependency)

2. In `gateway/session.py` `RoomSession.create()`:
   - Lazily create a `ConversationSession` via `MemoryService().start_session()`
   - Set `tool_ctx.session_id` to the session UUID
   - Pass `on_extract=lambda text, sid: PipelineRunner().run(text, session_id=sid)`
     to `ReasoningAgent`

3. The `PipelineRunner` already exists and works (`pipeline/runner.py`):
   - Filter → KnowledgeExtractor (Gemini structured output) → Consolidator → Neo4j + Postgres
   - No changes needed to the pipeline itself — just wire the trigger

**What NOT to wire yet:**

- ObservationEngine / WorkingMemory — skip for now, `tool_ctx.last_face` works fine
- TextEmbedder / TextIndex — skip, facts go to Postgres but aren't embeddable yet
- ContextEngine — skip, system prompt stays static

**Test plan:**

1. Start worker, connect via dashboard/test script
2. Send prompt: "halo, nama saya Asep, saya suka sushi"
3. Wait for agent response (turn boundary triggers extraction)
4. Check Neo4j: `MATCH (p:Person {name:'Asep'})-[r:LIKES]->(x) RETURN x`
5. Check Postgres: `SELECT * FROM memory_facts WHERE content LIKE '%sushi%'`
6. Check Postgres: `SELECT * FROM conversation_messages WHERE content LIKE '%Asep%'`
7. Send prompt: "Asep kerja dimana?" — agent should answer via tool call to search_person

**Files to change:**

- `apps/backend/reasoning/agent/agent.py` — add `on_extract` param, wire `_on_turn()`
- `apps/backend/gateway/session.py` — create session_id, pass on_extract callback

**Estimated diff:** ~30 lines

---

### Step 2: Semantic Memory Retrieval (ContextEngine + Retriever)

**Goal:** Agent retrieves relevant memories at connect time and injects them into the
system prompt. "Siapa Asep?" → agent knows the answer without a tool call.

**Why second:** Depends on Step 1 — there needs to be data in the graph to retrieve.

**What to wire:**

1. In `gateway/session.py` `RoomSession.create()`:
   - Instantiate `TextEmbedder` (Gemini text embeddings, `perception/embeddings/text_embeddings.py`)
   - Instantiate `TextMemoryIndex` (FAISS for text, `packages/database/vector/text_index.py`)
   - Load existing facts from Postgres into the text index on startup

2. In `reasoning/agent/agent.py`:
   - Accept `engine: ContextEngine` in constructor
   - In `start()`, call `engine.build(current=None)` to get `(ContextPackage, text)`
   - Pass `context_text=text` to `session.connect(context_text=...)`

3. In `packages/shared/prompts/system.py`:
   - Add `{{context_package}}` placeholder back to `SYSTEM_INSTRUCTION`

4. In `reasoning/prompts/system.py`:
   - Restore `build_system_instruction()` to replace `{{context_package}}` with context_text

**Test plan:**

1. Ensure Step 1 has created Person:Asep with LIKES→sushi
2. Restart worker (so it loads facts + builds context at connect)
3. Send prompt: "siapa Asep?" — agent should answer "Asep suka sushi" from system prompt
4. No tool call needed — context is pre-injected

**Files to change:**

- `apps/backend/gateway/session.py` — instantiate TextEmbedder + TextIndex + ContextEngine
- `apps/backend/reasoning/agent/agent.py` — accept engine, call build() in start()
- `packages/shared/prompts/system.py` — add `{{context_package}}` placeholder
- `apps/backend/reasoning/prompts/system.py` — restore replace logic

**Estimated diff:** ~50 lines

---

### Step 3: Scene Understanding (fix memory leak first)

**Goal:** Agent knows where it is. "Dimana aku?" → "Anda di apotek."

**Why third:** The Gemini Vision memory leak (~100MB/min) must be fixed first.
This is the last perception module to re-enable.

**What to fix first:**
The `google-genai` client accumulates internal state across `generate_content` calls.
Fix: create a **new `genai.Client` per call** (or per N calls, like the ONNX session
recycle). The client is lightweight to construct; the leak is in the internal
HTTP connection pool + response cache.

**What to wire:**

1. In `perception/scene/understander.py`:
   - Fix: create a new `genai.Client` per `understand()` call, or recycle every N calls
   - Alternative: use `httpx.AsyncClient` directly with the Gemini REST API (bypass genai client)

2. In `gateway/session.py` `RoomSession.create()`:
   - Instantiate `SceneUnderstander`

3. In `gateway/livekit/track_handler.py` video loop:
   - Every N frames (e.g. every 5th frame = every 10s at 0.5 FPS), call
     `scene_understander.understand(jpeg)` → write result to `tool_ctx.last_scene`
   - Don't emit to ObservationEngine (we're not re-enabling that yet) — direct dict
     like `last_face`

4. In `tools/observation/tools.py`:
   - `current_scene` reads from `ctx.last_scene` instead of returning `{"available": False}`
   - `current_activity` reads from `ctx.last_scene`

5. In `tools/registry.py`:
   - Add `last_scene: dict | None = None` to `ToolContext`

**Test plan:**

1. Point camera at a recognizable location (kitchen, pharmacy, office)
2. Send prompt: "dimana aku?" — agent calls `current_scene` → returns location
3. Check worker log: `scene understood: {location: "kitchen", ...}`
4. Monitor memory: should stay stable for 5+ minutes (leak fix verified)

**Files to change:**

- `apps/backend/perception/scene/understander.py` — fix client leak
- `apps/backend/gateway/session.py` — instantiate SceneUnderstander
- `apps/backend/gateway/livekit/track_handler.py` — call scene understander in video loop
- `apps/backend/tools/registry.py` — add `last_scene` to ToolContext
- `apps/backend/tools/observation/tools.py` — read from `last_scene`

**Estimated diff:** ~60 lines

---

### Step 4: Proactive Planner

**Goal:** Agent proactively reminds user about pending tasks when context matches.
Entering a pharmacy → "Jangan lupa beli paracetamol."

**Why fourth:** Depends on scene understanding (Step 3) for location context.

**What to wire:**

1. In `gateway/session.py` `RoomSession.create()`:
   - Instantiate `ProactivePlanner(reminder_service=..., shopping_service=...)`

2. In `reasoning/agent/agent.py`:
   - Accept `planner` in constructor
   - In `start()`, call `planner.start(self._get_context, self._on_proactive)`
   - `_get_context()` returns a `CurrentContext` built from `tool_ctx.last_face`
     and `tool_ctx.last_scene` (simple dict → CurrentContext, no WorkingMemory needed)
   - `_on_proactive(text)` calls `session.send_text(text)` to inject a proactive prompt

3. In `reasoning/agent/agent.py` `stop()`:
   - Call `planner.stop()`

**Test plan:**

1. Create a reminder: "ingatkan saya beli paracetamol" (agent calls create_reminder)
2. Point camera at a pharmacy/pharmacy-like scene
3. Wait 30s (planner interval)
4. Agent should proactively say: "Jangan lupa beli paracetamol"
5. Check worker log: `planner trigger: reminder=paracetamol location=apotek`

**Files to change:**

- `apps/backend/gateway/session.py` — instantiate ProactivePlanner
- `apps/backend/reasoning/agent/agent.py` — accept planner, wire start/stop

**Estimated diff:** ~30 lines

---

### Step 5 (optional): Observation Engine + Working Memory

**Goal:** Restore the full perception fusion architecture from the PRD.

**Why last / optional:** The bare-minimum's direct dict approach (`tool_ctx.last_face`,
`tool_ctx.last_scene`) works well for a single-user demo. The ObservationEngine adds:

- 1s fusion window (dedup observations from multiple sources)
- 30s TTL on context (stale context expires)
- Single write path (no race conditions)
- Device telemetry processing (battery, button, wifi)

This is architecturally cleaner but not visible to the user. Only re-enable if:

- Multi-sensor fusion is needed (e.g. GPS + IMU + face + scene)
- Device telemetry needs to trigger actions (low battery alert)
- The direct dict approach proves insufficient

**What to wire:**

1. In `gateway/session.py`:
   - Instantiate `WorkingMemory` + `ObservationEngine(working_memory)`
   - Call `obs_engine.start()` in `session.start()`
   - Call `obs_engine.stop()` in `session.stop()`

2. In `gateway/livekit/track_handler.py`:
   - Emit `FaceObservation` to `obs_engine.emit()` instead of writing to `tool_ctx.last_face`
   - Emit `SceneObservation` to `obs_engine.emit()` instead of writing to `tool_ctx.last_scene`

3. In `gateway/livekit/entrypoint.py`:
   - Parse device telemetry from "device" topic → emit `DeviceObservation`

4. In `tools/registry.py`:
   - Replace `last_face` dict with `current_context: CurrentContext | None`
   - `current_face_embedding()` reads from `current_context.observations`
   - `device_snapshot()` reads from `current_context.device`

5. In `reasoning/agent/agent.py`:
   - `_on_transcription()` emits `SpeechObservation` to `obs_engine.emit()`
   - `_on_turn()` reads speech from `current_context.speech`

6. Call `session.sync_context()` after each frame to push CurrentContext to ToolContext.

**Test plan:**

1. Same 10-step verification as Step 0
2. Verify face observations are fused (not lost between frames)
3. Verify device telemetry (battery %, button press) appears in context
4. Verify 30s TTL: stop camera for 35s, check `current_context` returns None

**Files to change:**

- `apps/backend/gateway/session.py`
- `apps/backend/gateway/livekit/track_handler.py`
- `apps/backend/gateway/livekit/entrypoint.py`
- `apps/backend/tools/registry.py`
- `apps/backend/reasoning/agent/agent.py`

**Estimated diff:** ~80 lines

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
| `apps/backend/gateway/session.py`                       | RoomSession — wires all components per room          |
| `apps/backend/gateway/livekit/entrypoint.py`            | LiveKit job handler — room connection + track wiring |
| `apps/backend/gateway/livekit/track_handler.py`         | Video/audio track → perception + reasoning           |
| `apps/backend/reasoning/agent/agent.py`                 | ReasoningAgent — Gemini Live + tool dispatch         |
| `apps/backend/reasoning/session/live_session.py`        | GeminiLiveSession — WS connection + receive loop     |
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
| `packages/config/env/settings.py`                       | Settings — all env config (single source of truth)   |

---

## What the Full Product Looks Like (after all steps)

```
Video frame
  → FrameSampler (0.5 FPS)
  → FaceRecognizer → FaceRepository.lookup → tool_ctx.last_face
  → SceneUnderstander → tool_ctx.last_scene          (Step 3)

Audio
  → SpeechForwarder → Gemini Live (realtime audio in)

Prompt (data channel)
  → agent.feed_prompt() → Gemini Live (text in)

Gemini Live
  → tool_call → ToolRouter → tool_ctx (last_face, last_scene, services)
  → tool_result → response
  → output_transcription → Display (OLED)
  → audio → Speaker

Turn boundary
  → _on_turn() → PipelineRunner.run(text, session_id)  (Step 1)
    → KnowledgeExtractor (Gemini structured output)
    → Consolidator → Neo4j (graph) + Postgres (episodic + facts)

Agent start
  → ContextEngine.build() → context_text              (Step 2)
    → Retriever (Neo4j + Postgres + TextIndex)
    → Ranker
    → Summarizer (Gemini)
  → system prompt with context package

Proactive loop (every 30s)                              (Step 4)
  → ProactivePlanner.check_context()
  → if reminder matches scene → send_text("Jangan lupa...")
```

This matches the proposal's Appendix A.10 end-to-end workflow.
