# Cut Functionality — Proposal vs Bare-Minimum

**Branch:** `refactor/bare-minimum`
**Date:** 2026-08-11

This document maps every feature described in the proposal
(`docs/proposal/main-proposal.md`) to its current status in the
`refactor/bare-minimum` branch. Features are grouped by the proposal's
architecture layers. Each entry notes what was cut, why, and the exact
re-enable path.

---

## Proposal Architecture (6 subsystems)

The proposal describes six major subsystems (Appendix A.1):

1. Smart Wearable Device
2. Realtime Communication Layer
3. Perception Layer
4. Working Memory & Memory Pipeline
5. Memory OS
6. Reasoning Layer

The bare-minimum refactor keeps subsystems 1, 2, 3 (partial), and 6.
Subsystems 4 and 5 are bypassed.

---

## 1. Smart Wearable Device (ESP32-S3)

| Proposal feature   | Status       | Notes                                                                                                                           |
| ------------------ | ------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| OV2640 camera      | **Kept**     | Streams video via LiveKit                                                                                                       |
| Microphone         | **Kept**     | Streams audio via LiveKit                                                                                                       |
| OLED display       | **Kept**     | Receives display text via LiveKit data channel                                                                                  |
| Battery / charging | **Bypassed** | Device telemetry (battery %, wifi, button) is logged but not processed — no observation engine to emit `DeviceObservation` into |
| Firmware commands  | **N/A**      | Not implemented in MVP                                                                                                          |

### What was cut

**Device telemetry processing** (Appendix A.3 — Data Channel): The proposal
describes bidirectional data channel messages for "user interaction events,
reminder notifications, recognized identities, display instructions, and future
firmware commands." The `handle_data_received` function in
`gateway/livekit/data_channel.py` parsed device telemetry JSON
(`{battery_level, wifi_connected, button_pressed}`) and emitted
`DeviceObservation` into the observation engine. In bare-minimum, the
entrypoint just logs device telemetry — no parsing, no observation.

**Re-enable:** Wire `handle_data_received(data, topic, session.observation_engine)`
back into `entrypoint.py` `_on_data`. Requires re-enabling ObservationEngine
(see section 4 below).

---

## 2. Realtime Communication Layer (LiveKit)

| Proposal feature           | Status      | Notes                                               |
| -------------------------- | ----------- | --------------------------------------------------- |
| Video track                | **Kept**    | FrameSampler at 1 FPS                               |
| Audio track                | **Kept**    | SpeechForwarder → Gemini Live                       |
| Data channel (inbound)     | **Partial** | Prompt topic works; device telemetry logged only    |
| Data channel (outbound)    | **Kept**    | Display topic publishes model text to OLED          |
| Voice response (audio out) | **Kept**    | Speaker publishes Gemini PCM as LiveKit audio track |

**Nothing cut from this layer.** All three LiveKit channels (video, audio,
data) remain functional. The only change is that inbound device telemetry on
the data channel is logged instead of processed.

---

## 3. Perception Layer

### 3.1 Face Recognition (InsightFace + FAISS)

| Proposal feature                       | Status   | Notes                                               |
| -------------------------------------- | -------- | --------------------------------------------------- |
| Face detection                         | **Kept** | InsightFace buffalo_l, CPU, lazy-loaded             |
| Face alignment                         | **Kept** | Handled by InsightFace internally                   |
| Face embedding (512-d)                 | **Kept** | L2-normalized embeddings                            |
| FAISS similarity search                | **Kept** | FaceRepository.lookup() with cosine similarity      |
| Face registration (`register_face`)    | **Kept** | Persists to FAISS + Postgres                        |
| Auto-register on `search_person` match | **Kept** | If 1 Person match + unknown face, auto-registers    |
| Person graph lookup (Neo4j)            | **Kept** | `PersonRepo.get_person()` resolves person_id → name |

**Nothing cut from face recognition.** This is the core identity path and
remains fully functional.

### 3.2 Scene Understanding (Gemini Vision)

| Proposal feature           | Status  | Notes                              |
| -------------------------- | ------- | ---------------------------------- |
| Current location detection | **Cut** | SceneUnderstander not instantiated |
| Visible objects            | **Cut** | Same                               |
| Ongoing activities         | **Cut** | Same                               |
| Environmental context      | **Cut** | Same                               |

**What was cut:** The proposal (Appendix A.4.2) describes Gemini Vision
analyzing the surrounding environment to understand location, objects,
activities, and environmental context. The `SceneUnderstander` class
(`perception/scene/understander.py`) called Gemini Vision every 2 seconds
with a JPEG frame. This caused a memory leak of ~100MB/min (the google-genai
client accumulates internal state). The scene understander was first disabled
(`_SCENE_INTERVAL = 999999`) and then fully bypassed (not instantiated in
`RoomSession.create()`).

The `current_scene` and `current_activity` tools now return
`{"available": False}`. The system prompt tells the agent to call these tools,
but they will return no data.

**Re-enable:**

1. Fix the Gemini Vision client memory leak (likely need to create a new
   `genai.Client` per call or use a different API surface).
2. Instantiate `SceneUnderstander` in `RoomSession.create()`.
3. Re-wire the scene understander call in `track_handler.py` video loop.
4. Re-wire `SceneObservation` emission into the observation engine (or write
   directly to `tool_ctx.last_scene`).
5. Update `current_scene` / `current_activity` tools to read from `last_scene`.

### 3.3 Speech Recognition (Speech-to-Text)

| Proposal feature                           | Status   | Notes                                              |
| ------------------------------------------ | -------- | -------------------------------------------------- |
| Audio streaming to Gemini Live             | **Kept** | SpeechForwarder → _AudioShim → agent.feed_audio    |
| Input transcription (Gemini Live)          | **Kept** | `input_transcription` handled in live_session      |
| Output transcription (Gemini Live)         | **Kept** | `output_transcription` → Display (OLED)            |
| Speech → SpeechObservation → WorkingMemory | **Cut**  | `_on_transcription` just logs, no observation emit |

**What was cut:** The proposal (Appendix A.4.3) describes speech being
converted to text as "one of the primary inputs for long-term memory
formation." In the original architecture, final speech transcripts were
emitted as `SpeechObservation` into the `ObservationEngine`, which fused them
into `CurrentContext.speech`. The `on_extract` hook then used
`ctx.speech` at turn boundaries to trigger memory consolidation.

In bare-minimum, `_on_transcription` in `ReasoningAgent` just logs the
transcript. No `SpeechObservation` is emitted. The Gemini Live model still
receives audio in real-time and transcribes it — the transcription just
doesn't flow into the memory pipeline.

**Re-enable:** Wire `emit_observation` callback back into `ReasoningAgent`
constructor. Pass `obs_engine.emit` as the callback. In `_on_transcription`,
emit `SpeechObservation(transcript=text, confidence=0.9)` for final
transcripts. Requires re-enabling ObservationEngine (section 4).

---

## 4. Working Memory & Memory Pipeline

### 4.1 Working Memory

| Proposal feature                                | Status  | Notes                                               |
| ----------------------------------------------- | ------- | --------------------------------------------------- |
| Current context (visible people, scene, speech) | **Cut** | Replaced by `tool_ctx.last_face` dict               |
| 30s TTL context                                 | **Cut** | No WorkingMemory instance                           |
| ObservationEngine fusion (1s window)            | **Cut** | Face result writes directly to `tool_ctx.last_face` |
| Tool context sync                               | **Cut** | No `session.sync_context()` call                    |

**What was cut:** The proposal (Appendix A.5) describes Working Memory as
storing "visible people, current conversation, environmental context, user
requests, and recently recognized objects." The `ObservationEngine` was an
async queue that batched observations over a 1-second fusion window and
folded them into a `CurrentContext` object. The `WorkingMemory` held this
context with a 30s TTL. The video loop called `session.sync_context()` after
each frame to push the latest context into `ToolContext.current_context`.

This was a major source of nondeterminism:

- The 1s fusion window meant face observations could be lost if the person
  moved between windows.
- `CurrentContext.observations` was a list that tools had to iterate to find
  the latest embedding — fragile and indirect.
- The async queue added latency between face detection and tool availability.

In bare-minimum, the video loop writes the face result directly to
`tool_ctx.last_face` — a plain dict. No queue, no fusion, no TTL.

**Re-enable:**

1. Instantiate `WorkingMemory` and `ObservationEngine` in
   `RoomSession.create()`.
2. Call `obs_engine.start()` in `session.start()`.
3. In `track_handler.py`, emit `FaceObservation` to `obs_engine.emit()`
   instead of writing to `tool_ctx.last_face`.
4. Call `session.sync_context()` after each frame.
5. In `ToolContext`, replace `last_face` with `current_context` and update
   `current_face_embedding()` to iterate observations.

### 4.2 Memory Pipeline (Extraction → Classification → Consolidation)

| Proposal feature                      | Status  | Notes                                          |
| ------------------------------------- | ------- | ---------------------------------------------- |
| Memory Extraction                     | **Cut** | `on_extract` is a no-op                        |
| Memory Classification                 | **Cut** | Not triggered (depends on extraction)          |
| Memory Consolidation                  | **Cut** | Not triggered (depends on classification)      |
| ConversationSession (lazy DB session) | **Cut** | Not created                                    |
| Retroactive fact linking              | **Cut** | `register_person` no longer links orphan facts |

**What was cut:** The proposal (Appendix A.6) describes a three-stage memory
pipeline: extraction (identify meaningful facts from conversations),
classification (categorize into semantic entities), and consolidation (update
existing knowledge, remove duplicates, preserve history with timestamps).

In the original architecture, `ReasoningAgent._on_turn()` fired at turn
boundaries (when Gemini finished responding). It read the latest speech from
`CurrentContext.speech` and passed it to the `on_extract` hook, which ran
`PipelineRunner(consolidator).run(text, session_id)`. The `ConversationSession`
was lazily created on the first turn (a Postgres record for episodic memory).
`register_person` retroactively linked orphan facts from the current session
to the newly-identified person.

In bare-minimum, `_on_turn()` is a no-op. No extraction, classification, or
consolidation occurs. Conversations are not persisted. The
`ConversationSession` is never created. `register_person` still works (creates
a Neo4j node) but doesn't link facts.

**Re-enable:**

1. Pass `on_extract` callback to `ReasoningAgent` constructor.
2. In `_on_turn()`, read speech from `tool_ctx.current_context.speech`
   (requires WorkingMemory re-enabled).
3. Lazily create `ConversationSession` via `MemoryService().start_session()`.
4. Run `PipelineRunner(consolidator).run(text, session_id)`.
5. Requires `TextEmbedder` + `TextIndex` for semantic consolidation.

---

## 5. Memory OS

### 5.1 Semantic Memory

| Proposal feature                         | Status      | Notes                                                                                            |
| ---------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------ |
| Person names, occupations, relationships | **Partial** | Neo4j stores Person nodes + relationships; `search_person`, `get_person`, `register_person` work |
| Preferences, places, routines            | **Cut**     | Not extracted (memory pipeline bypassed)                                                         |
| Knowledge Graph queries                  | **Kept**    | Neo4j is connected, `PersonRepo` works                                                           |
| Context retrieval (Retriever)            | **Cut**     | `ContextEngine` + `Retriever` not instantiated                                                   |
| Memory ranking                           | **Cut**     | No retrieval → no ranking                                                                        |

**What was cut:** The proposal (Appendix A.7.2) describes semantic memory
storing "names, occupations, relationships, personal preferences, frequently
visited places, and important routines." The Neo4j graph stores Person nodes
and relationships, and the `search_person` / `get_person` / `register_person`
tools work. But facts like preferences, places, and routines are never
extracted from conversations (memory pipeline is bypassed).

The `ContextEngine` + `Retriever` were responsible for retrieving relevant
memories at agent connect time. The `ContextEngine.build(current)` call
generated a context package (Bahasa text) injected into the system prompt. In
bare-minimum, the system prompt is static — no retrieved context.

**Re-enable:**

1. Instantiate `TextEmbedder` + `TextMemoryIndex` in `RoomSession.create()`.
2. Pass `text_embedder` + `text_index` to `ReasoningAgent`.
3. Re-build `ContextEngine(retriever=Retriever(...))` in agent constructor.
4. Call `engine.build(current)` in `agent.start()` to generate context text.
5. Pass context text to `session.connect(context_text=...)`.
6. Re-enable memory pipeline (section 4.2) to populate semantic memory.

### 5.2 Episodic Memory

| Proposal feature                  | Status   | Notes                                                                       |
| --------------------------------- | -------- | --------------------------------------------------------------------------- |
| Conversation history              | **Cut**  | No ConversationSession, no DB persistence                                   |
| Chronological interaction records | **Cut**  | Same                                                                        |
| `conversation_summary` tool       | **Kept** | Calls `MemoryService.recent_memories()` — returns empty without DB sessions |
| `search_memory` tool              | **Kept** | Calls `MemoryService.search_memories()` — returns empty without DB sessions |
| `memory_timeline` tool            | **Kept** | Same — returns empty                                                        |

**What was cut:** The proposal (Appendix A.7.3) describes episodic memory as
"chronological records of previous interactions, conversations, and
experiences." In the original architecture, `ConversationSession` records
were created in Postgres, and `PipelineRunner` consolidated conversation text
into episodic memory entries. The `conversation_summary`, `search_memory`, and
`memory_timeline` tools query these records.

In bare-minimum, no conversation sessions are created, so these tools return
empty results. The tools themselves still work — they just have no data to
return.

**Re-enable:** Re-enable memory pipeline (section 4.2). ConversationSession is
lazily created on the first turn. `PipelineRunner` consolidates conversation
text into episodic memory.

### 5.3 FAISS Face Index

| Proposal feature          | Status   | Notes                                                                |
| ------------------------- | -------- | -------------------------------------------------------------------- |
| Face embedding storage    | **Kept** | FAISS IndexFlatIP, cosine similarity                                 |
| Postgres persistence      | **Kept** | `FaceEmbeddingRepo.save()` + `FaceEmbeddingRepo.load_all()`          |
| Cross-restart recognition | **Kept** | `FaceRepository.from_db()` loads embeddings from Postgres on startup |

**Nothing cut from face index.** This is core infrastructure and remains
fully functional.

---

## 6. Reasoning Layer

### 6.1 Gemini Live

| Proposal feature                   | Status   | Notes                                                      |
| ---------------------------------- | -------- | ---------------------------------------------------------- |
| Natural voice interaction          | **Kept** | Audio in/out via LiveKit + Gemini Live                     |
| Tool calling                       | **Kept** | All tools registered and dispatched                        |
| Output transcription → display     | **Kept** | `output_transcription` → Display → OLED                    |
| Non-blocking connect               | **Kept** | Background task with retry                                 |
| Reconnect with backoff             | **Kept** | Receive loop reconnects on connection drop                 |
| Conversation history re-injection  | **Kept** | `_recent_turns` (last 6 turns) re-injected after reconnect |
| System prompt with context package | **Cut**  | Static system prompt, no `{{context_package}}`             |

**What was cut:** The proposal (Appendix A.9) describes the reasoning engine
receiving "Current Working Memory, Retrieved Semantic Memory, Relevant
Episodic Memory, and User query." In the original architecture, the
`ContextEngine.build()` call generated a context package from retrieved
memories and current context, which was injected into the system prompt at
connect time via the `{{context_package}}` placeholder.

In bare-minimum, the system prompt is static. The agent gets context by
calling tools (`visible_people`, `current_scene`, `search_memory`, etc.) —
which is the same mechanism the proposal describes for dynamic context. The
only difference is that the initial system prompt doesn't contain a pre-built
context package.

**Re-enable:** Add `{{context_package}}` back to `SYSTEM_INSTRUCTION` in
`packages/shared/prompts/system.py`. Restore `build_system_instruction()` to
do the replace. Pass dynamic `context_text` from `ContextEngine.build()` to
`session.connect(context_text=...)`.

### 6.2 Proactive Planner

| Proposal feature                                             | Status   | Notes                                                      |
| ------------------------------------------------------------ | -------- | ---------------------------------------------------------- |
| Proactive everyday assistance                                | **Cut**  | ProactivePlanner not started                               |
| Context-aware reminders (e.g. "buy paracetamol" at pharmacy) | **Cut**  | No planner to check context vs reminders                   |
| Reminder scheduling                                          | **Kept** | `reminder_service` works (create/list reminders via tools) |
| Shopping list management                                     | **Kept** | `shopping_service` works (add/list items via tools)        |
| Calendar events                                              | **Kept** | `event_service` works (create/list events via tools)       |

**What was cut:** The proposal (Core Feature #3) describes proactive
assistance: "the assistant continuously tracks daily intentions and important
activities. It can remind users about shopping lists, medications,
appointments, meetings, unfinished tasks, or personal commitments when they
become contextually relevant." The `ProactivePlanner` was a periodic background
task that checked the current context against pending reminders and triggered
a proactive prompt if relevant.

In bare-minimum, the planner is not started. Reminders, shopping lists, and
calendar events can still be created and queried via tool calls — but the
agent won't proactively remind the user. The user has to ask.

**Re-enable:**

1. Instantiate `ProactivePlanner` in `RoomSession.create()`.
2. Pass `planner` to `ReasoningAgent` constructor.
3. Call `planner.start(self._get_context, self._on_proactive)` in
   `agent.start()`.
4. `_get_context` needs `tool_ctx.current_context` (requires WorkingMemory).
5. `_on_proactive` sends a proactive prompt via `session.send_text()`.

---

## 7. Caregiver Dashboard

| Proposal feature                         | Status   | Notes                                                         |
| ---------------------------------------- | -------- | ------------------------------------------------------------- |
| Real-time activity logs                  | **N/A**  | Dashboard is a Next.js app, not affected by backend refactor  |
| Disorientation alerts                    | **N/A**  | Not implemented in MVP                                        |
| Multi-caregiver shared access            | **N/A**  | Not implemented in MVP                                        |
| Device harness (token, connect, publish) | **Kept** | Dashboard connects to LiveKit, mints tokens, dispatches agent |

**Not affected by this refactor.** The dashboard is a separate Next.js app
that connects to LiveKit. The backend refactor doesn't change the dashboard's
API surface (token route, LiveKit connection, data channel topics).

---

## Summary: What Works vs What's Cut

### Works in bare-minimum

- User wears glasses, camera + mic stream to LiveKit
- Agent connects to room via LiveKit dispatch
- Gemini Live connects (non-blocking, retries in background)
- User sends text prompt → agent responds with audio + OLED text
- Face detection runs at 1 FPS via InsightFace
- Face result writes directly to `tool_ctx.last_face`
- Agent calls `search_person_by_face` → recognizes known faces
- Agent calls `search_person` → finds people in Neo4j by name
- Agent calls `register_person` → creates Person node in Neo4j
- Agent calls `register_face` → saves embedding to FAISS + Postgres
- Agent calls `get_person` → returns full profile + relationships
- Face embeddings persist across restarts (Postgres → FAISS on startup)
- Reminders, shopping lists, calendar events (create/list via tools)
- Audio out (Gemini PCM → LiveKit audio track → glasses speaker)
- Display out (model text → LiveKit data channel → OLED)

### Cut in bare-minimum

- Scene understanding (location, objects, activities) — Gemini Vision leak
- Memory extraction from conversations — no pipeline runner
- Memory classification — no extraction
- Memory consolidation — no extraction
- Episodic memory persistence — no conversation sessions
- Semantic memory retrieval at connect — no ContextEngine/Retriever
- Context package in system prompt — static prompt only
- Proactive reminders — no planner
- Device telemetry processing — logged, not emitted
- Observation fusion — direct dict assignment
- Working memory TTL — no WorkingMemory
- Speech → observation feed — transcription logged only
- Retroactive fact linking on `register_person` — no session

---

## Re-enable Order

To incrementally re-enable cut functionality, follow this dependency order:

```
1. ObservationEngine + WorkingMemory
   └── enables: device telemetry, speech observations, face observation fusion
   └── requires: nothing

2. Memory Pipeline (extraction → classification → consolidation)
   └── enables: episodic memory, fact extraction from conversations
   └── requires: ObservationEngine (for speech in CurrentContext)

3. TextEmbedder + TextIndex + ContextEngine + Retriever
   └── enables: semantic memory retrieval, context package in system prompt
   └── requires: Memory Pipeline (for data to retrieve)

4. ProactivePlanner
   └── enables: proactive reminders based on context
   └── requires: WorkingMemory (for current context), reminder service

5. SceneUnderstander (fix memory leak first!)
   └── enables: location, objects, activities
   └── requires: ObservationEngine (for SceneObservation fusion)
```

Each layer can be re-enabled independently once the layer below it is stable.
Test the core flow (face recognition + conversation) after each layer before
adding the next.
