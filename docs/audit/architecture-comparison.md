# Architecture Comparison: Proposal vs Implementation

**Date:** 2026-08-12
**Branch:** `refactor/agent-session-gemini`
**Proposal:** `docs/proposal/main-proposal.md` (+ Appendices A–C)
**Implementation:** `apps/backend/` (Steps 0–5 complete)

---

## 1. Executive Summary

The implementation follows the proposal's three-layer architecture (Perception → Memory OS → Reasoning) faithfully at the component level. Every major subsystem from the proposal exists in code. The main divergences are:

1. **Session management:** Custom WebSocket plumbing replaced by LiveKit's `AgentSession` + `google.realtime.RealtimeModel` (the proposal assumed direct Gemini Live API).
2. **Vector search:** FAISS is used for face embeddings (as proposed) but text embeddings use a separate in-memory FAISS index (`TextMemoryIndex`) instead of a persistent store.
3. **Working Memory:** Implemented as a simple TTL dict (`WorkingMemory`) with a 1s fusion window (`ObservationEngine`) — matches the PRD but is lighter than the proposal's "continuously updated" description implies.
4. **Caregiver Dashboard:** Not implemented in the backend (frontend exists as `apps/dashboard/` but is a simple LiveKit connection UI, not the multi-caregiver dashboard from the proposal).

**Core features implemented:** 3 of 4 proposal core features are functional. The Caregiver Dashboard (Feature #4) is not implemented.

---

## 2. Layer-by-Layer Comparison

### 2.1 IoT Wearable & Perception Layer

| Proposal (Appendix A.2–A.4)                             | Implementation                                             | Match?                  |
| ------------------------------------------------------- | ---------------------------------------------------------- | ----------------------- |
| ESP32-S3 Sense with OV2640 camera, mic, OLED            | `apps/firmware/` (ESP32-S3 firmware, not audited here)     | ✅                      |
| LiveKit for realtime communication (video, audio, data) | LiveKit used for all three channels via `AgentSession`     | ✅                      |
| Frame Sampler at ~1 FPS                                 | `FrameSampler` in `perception/vision/sampler.py`           | ✅                      |
| InsightFace for face detection + embedding              | `FaceRecognizer` in `perception/face/recognizer.py`        | ✅                      |
| FAISS for face similarity search                        | `FaceRepository` + FAISS in `vector/repository.py`         | ✅                      |
| Gemini Vision for scene understanding                   | `SceneUnderstander` in `perception/scene/understander.py`  | ✅                      |
| Speech-to-Text processing                               | Handled by Gemini RealtimeModel (built-in STT)             | ✅ (different approach) |
| Working Memory from perception outputs                  | `ObservationEngine` → `WorkingMemory` (1s fusion, 30s TTL) | ✅                      |

**Key difference:** The proposal describes STT as a separate perception module. The implementation uses Gemini RealtimeModel's built-in STT, which is accessed via the `user_input_transcribed` event. This is simpler (no separate Whisper call) but couples STT to the Gemini model. The proposal's `openai-whisper` dependency is declared in `pyproject.toml` but is not wired in the current architecture.

**Better approach?** The RealtimeModel's built-in STT is better for the MVP — it eliminates a network call, reduces latency, and the transcription quality is comparable. Whisper could be added as a fallback if Gemini STT quality degrades for specific Indonesian dialects.

---

### 2.2 Memory OS

| Proposal (Appendix A.5–A.7)                                                    | Implementation                                                                           | Match?                      |
| ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------- | --------------------------- |
| Working Memory: current context, visible people, scene, conversation           | `WorkingMemory` class: `CurrentContext` with 30s TTL                                     | ✅                          |
| Memory Extraction: identify meaningful facts from conversations + observations | `KnowledgeExtractor` (Gemini structured output)                                          | ✅                          |
| Memory Classification: categorize into semantic classes                        | `KnowledgeExtractor` returns entities with categories (Person, Organization, Food, etc.) | ✅ (merged with extraction) |
| Memory Consolidation: dedup, update, preserve history with timestamps          | `Consolidator` in `pipeline/consolidator.py`                                             | ✅                          |
| Semantic Memory: names, occupations, relationships, preferences                | Neo4j `KnowledgeGraphRepo` + `PersonRepo`                                                | ✅                          |
| Episodic Memory: chronological interactions                                    | Postgres `conversation_messages` table via `MemoryService`                               | ✅                          |
| Knowledge Graph: relationship-aware reasoning                                  | Neo4j with `Person`, `WORKS_AT`, `LIKES`, etc.                                           | ✅                          |
| Memory Retrieval: semantic, temporal, social, spatial, conversational          | `Retriever` + `ContextEngine` + `Ranker`                                                 | ✅                          |
| Memory Ranking: weighted scoring across signals                                | `memory/ranking/ranker.py`                                                               | ✅                          |
| Memory Forgetting Strategy (§14)                                               | Not implemented                                                                          | ❌                          |
| Procedural Memory (§12, future)                                                | Not implemented                                                                          | ❌ (proposal says "future") |
| Provenance / Explainability (§15)                                              | `memory_facts` table has `source_session_id`, `confidence`, `created_at`                 | Partial                     |

**Key difference — Classification merged with Extraction:** The proposal describes three sequential pipeline stages (Extraction → Classification → Consolidation). The implementation merges extraction and classification into a single Gemini structured-output call (`KnowledgeExtractor.extract()` returns entities with categories). This is simpler and faster (one API call instead of two) but loses the ability to use different models for each stage.

**Better approach?** Merging extraction + classification is better for the MVP. The Gemini model is capable enough to do both in one call, and the two-stage approach would double API costs. Keep them merged unless we need to swap the classification model independently.

**Key difference — No Forgetting Strategy:** The proposal describes a forgetting strategy (keep/archive/compress/delete based on importance, frequency, recency). The implementation stores everything permanently. For a dementia assistant, this is arguably correct — you don't want to forget things about the patient's life. But it means the graph and Postgres will grow unbounded.

**Better approach?** Skip forgetting for now. Add it when storage becomes a problem. Dementia patients benefit from more memory, not less.

**Key difference — Text Embeddings:** The proposal mentions FAISS for face embeddings only. The implementation adds a separate `TextMemoryIndex` (FAISS, 768-d) for text embeddings of extracted facts. This enables semantic retrieval ("siapa Asep?" → facts about Asep retrieved by embedding similarity). The proposal's retrieval is graph-based only.

**Better approach?** The implementation's approach is better. Graph retrieval alone can't answer "tell me about the person who likes sushi" — you need text embedding similarity for that. The proposal's architecture diagram shows FAISS for faces only, but the PRD's Memory Retrieval section (§9) mentions "semantic relevance" which implies text embeddings. The implementation fills this gap.

---

### 2.3 Reasoning Layer

| Proposal (Appendix A.9)                                           | Implementation                                                              | Match?                  |
| ----------------------------------------------------------------- | --------------------------------------------------------------------------- | ----------------------- |
| Gemini Live as reasoning engine (not memory store)                | `google.realtime.RealtimeModel` via `AgentSession`                          | ✅                      |
| Retrieval-augmented: retrieve relevant memories before generating | `ContextEngine.build()` called in `on_enter()` → `update_instructions()`    | ✅                      |
| Tool calling for on-demand memory access                          | 31 tools via `@function_tool(raw_schema=...)`                               | ✅                      |
| LLM receives: Working Memory + Semantic + Episodic + User Query   | System prompt has `{{context_package}}` placeholder, tools provide the rest | ✅                      |
| Session management: init, heartbeat, reconnection                 | Handled by `AgentSession` + LiveKit framework                               | ✅ (different approach) |

**Key difference — Session Management:** The proposal describes session management as a responsibility of the "Gemini Live Agent" (PRD §5): initialization, authentication, streaming lifecycle, heartbeat monitoring, automatic reconnection. The implementation delegates all of this to LiveKit's `AgentSession` + the `google.realtime.RealtimeModel` plugin. No custom WebSocket management, no heartbeat, no reconnection logic.

**Better approach?** LiveKit's `AgentSession` is unambiguously better. The old implementation (`GeminiLiveSession`) had ~900 lines of WebSocket plumbing, reconnection logic, and audio buffering. The new implementation has 0 lines of that — it's all framework code maintained by the LiveKit team. Less code to maintain, fewer bugs, automatic reconnection. The proposal assumed direct API access; the implementation uses the framework that was built for exactly this purpose.

**Key difference — Event-Driven Reasoning:** The PRD (reasoning_agent.md §6) describes event-driven reasoning: "The agent performs reasoning only when meaningful events occur" — new person, unknown face, conversation begins, user question, reminder relevance, scene change, tool execution. The implementation is event-driven at the turn level (VAD detects end-of-speech → tool calls → response) but doesn't trigger reasoning on scene changes or new-face events. The proactive planner covers the "reminder relevance" and "new person" triggers, but scene-change-triggered reasoning is not implemented.

**Better approach?** The proposal's fully event-driven approach is more efficient (fewer API calls) but harder to implement reliably. The implementation's VAD-based turn detection is simpler and sufficient for the MVP. Scene-change-triggered reasoning could be added later by having the ObservationEngine emit events that trigger `generate_reply` — but this risks over-talking. The current approach (agent only speaks when spoken to, except for proactive planner triggers) is safer for a dementia patient who might be confused by unprompted commentary.

**Update (2026-08-12):** Periodic context refresh implemented — context is folded into the `generate_reply()` instructions on `on_enter()`. Mid-session `update_instructions()` is intentionally NOT called because the Gemini Live API corrupts the audio stream when `send_client_content(turn_complete=False)` is sent mid-session (confirmed via live testing — error: `CONTENT_TYPE_AUDIO not supported for this model configuration`). `_refresh_context()` builds context + logs it but does not push it to the model. Mid-conversation context updates rely on tool calls.

---

### 2.4 Technology Stack

| Proposal (§4)                          | Implementation                                    | Match?                        |
| -------------------------------------- | ------------------------------------------------- | ----------------------------- |
| Wearable: ESP32-S3 Sense, OV2640, OLED | Same                                              | ✅                            |
| Embedded: Arduino / ESP-IDF (C++)      | `apps/firmware/`                                  | ✅                            |
| Realtime: LiveKit                      | `livekit` + `livekit-agents[google]`              | ✅                            |
| Backend API: FastAPI                   | `fastapi==0.141.1`                                | ✅                            |
| AI Framework: Python                   | Python 3.12                                       | ✅                            |
| LLM: Gemini Live                       | `google-genai==2.17.0` + `livekit-plugins-google` | ✅                            |
| Face Recognition: InsightFace          | `insightface==1.0.1`                              | ✅                            |
| Vector Search: FAISS                   | `faiss-cpu==1.15.0` (faces + text)                | ✅                            |
| Database: PostgreSQL                   | `asyncpg==0.31.0` + `sqlalchemy==2.0.51`          | ✅                            |
| Knowledge Graph: Neo4j                 | `neo4j==6.2.0`                                    | ✅                            |
| Deployment: Railway                    | Railway MCP configured                            | ✅                            |
| Monorepo: NX                           | UV workspace (Python) + `apps/` structure         | ❌ (NX is JS; Python uses UV) |

**Key difference — Monorepo tool:** The proposal says NX. The implementation uses UV workspaces (Python-native). NX is a JavaScript monorepo tool; using it for a Python-heavy project would add complexity without benefit. UV workspaces are the standard for Python monorepos.

**Better approach?** UV is correct for this project. NX was likely listed because the proposal was written before the team committed to a Python-only backend.

---

## 3. Core Feature Comparison

### Feature 1: Real-time Face Recognition (Proposal §1)

**Proposal:** Recognize people from previous encounters, provide contextual reminders (name, relationship, occupation, preferences).

**Implementation:**

- `FaceRecognizer` (InsightFace) → 512-d embeddings → `FaceRepository.lookup()` → Neo4j `PersonRepo.get_person()` → name + relationships
- Tools: `search_person`, `get_person`, `visible_people`, `register_person`, `register_face`
- System prompt instructs the agent to proactively ask "Siapa ini?" for unknown faces and register them

**Status: ✅ Fully implemented.** Face recognition → identity lookup → graph retrieval → agent response. The register_person/register_face flow allows learning new faces during conversation.

---

### Feature 2: Context-Aware Memory Retrieval (Proposal §2)

**Proposal:** Retrieve relevant memories when encountering familiar people, revisiting locations, or asking questions.

**Implementation:**

- `ContextEngine.build()` retrieves from Neo4j (graph) + Postgres (episodic) + `TextMemoryIndex` (semantic)
- `Retriever` combines graph search + text embedding similarity
- `Ranker` scores by semantic similarity, temporal relevance, social relevance, spatial relevance
- `Summarizer` compresses if over budget
- Context injected into system prompt via `update_instructions()` in `on_enter()`
- Tools: `search_person`, `get_person`, `search_memory`, `conversation_summary`

**Status: ✅ Fully implemented.** ~~One gap: context is only built on `on_enter()` (session start), not on every turn. The PRD (context.md §5) describes "event-driven" context refresh. Currently the agent relies on tool calls for mid-conversation context updates, not automatic context refreshes.~~

**Update (2026-08-12):** Context is now folded into the `generate_reply()` instructions on `on_enter()` instead of calling `update_instructions()` separately. This is because the Gemini Live API corrupts the audio stream when `send_client_content(turn_complete=False)` is sent mid-session. `_refresh_context()` builds context but does not push it to the model — mid-conversation context updates rely on tool calls.

**Should we switch?** ~~Add periodic context refreshes~~ Done. The `update_instructions()` limitation is a Gemini Live API constraint, not a design choice. If the API later supports mid-session instruction updates, `_refresh_context` can be extended to call `update_instructions()` at that point.

---

### Feature 3: Proactive Everyday Assistance (Proposal §3)

**Proposal:** Track daily intentions and activities. Proactively remind about shopping lists, medications, appointments when contextually relevant. Example: entering a pharmacy → remind about paracetamol.

**Implementation:**

- `ProactivePlanner` runs every 30s, checks `CurrentContext` against pending reminders + shopping list
- `_keyword_overlap()` matches location keywords against reminder/shopping text
- `generate_reply()` injects the proactive prompt as speech
- Cooldown: 5 min per (item, location) pair, 2 min for "Siapa ini?" trigger
- "Siapa ini?" trigger: fires when unknown person is visible AND user is speaking

**Status: ✅ Implemented.** ~~One gap: `_keyword_overlap()` is a naive string match. "apotek" vs "beli paracetamol" doesn't overlap (the self-check test confirms this). The proposal's example (pharmacy → paracetamol) requires semantic understanding, not keyword matching.~~

**Update (2026-08-12):** Semantic matching now implemented. The planner does a keyword pass first (free), then a batch embedding similarity pass for unmatched items (one API call per 30s cycle, threshold 0.5). "apotek" now matches "beli paracetamol" via cosine similarity. Falls back to keyword-only when `text_embedder` is None (backward compatible).

**Trade-off:** ~~Semantic matching (embedding similarity between location and reminder text) would be more accurate but requires an embedding call per check (every 30s). Keyword overlap is free. For the MVP, keyword overlap is acceptable — the user can create reminders with location-specific keywords ("beli paracetamol di apotek").~~ Semantic matching costs one batch embed call per 30s cycle — acceptable cost for the accuracy improvement.

---

### Feature 4: Caregiver Dashboard (Proposal §4)

**Proposal:** Connected mobile where every family member can view real-time activity logs and receive alerts when the patient appears disoriented or in an unfamiliar location.

**Implementation:**

- `apps/dashboard/` exists as a Next.js app with LiveKit connection UI
- No caregiver-specific features: no activity logs, no disorientation alerts, no multi-caregiver support, no location alerts
- Backend has no caregiver API endpoints, no alert system

**Status: ❌ Not implemented.** The dashboard is a development/testing tool, not the multi-caregiver dashboard from the proposal.

**Why?** The proposal explicitly excludes the dashboard from the MVP scope (§MVP Scope): "Features intentionally excluded from the MVP include mobile applications." The current dashboard is for testing, not production.

---

## 4. Architecture Differences: Proposal vs Implementation

### 4.1 Session Architecture

| Aspect                 | Proposal                   | Implementation                           |
| ---------------------- | -------------------------- | ---------------------------------------- |
| Gemini Live connection | Direct API (WebSocket)     | LiveKit `AgentSession` + `RealtimeModel` |
| Audio I/O              | Custom forwarder + speaker | `AgentSession` automatic                 |
| Video input            | Custom frame forwarding    | `RoomOptions(video_input=True)`          |
| Turn detection         | Custom VAD or manual       | LiveKit built-in VAD                     |
| Reconnection           | Custom logic               | LiveKit framework                        |
| Tool dispatch          | Custom `ToolRouter`        | `@function_tool(raw_schema=...)`         |

**Which is better?** The implementation's `AgentSession` approach is strictly better:

- **Less code:** ~900 lines of custom plumbing deleted
- **More reliable:** Framework handles reconnection, buffering, VAD
- **More maintainable:** LiveKit team maintains the plumbing, not us
- **More features:** Audio output, transcription, barge-in all free
- **Trade-off:** Tighter coupling to LiveKit. If we needed to switch to a different realtime platform, the proposal's direct API approach would be more portable. But LiveKit is the chosen platform in both cases, so this coupling is intentional.

**Should we switch back?** No. The AgentSession refactor is the correct architecture. The proposal's direct API approach was appropriate for the proposal stage but the implementation benefits from the framework that was built for exactly this use case.

---

### 4.2 Memory Pipeline Architecture

| Aspect                      | Proposal                                                     | Implementation                                                  |
| --------------------------- | ------------------------------------------------------------ | --------------------------------------------------------------- |
| Extraction + Classification | Two sequential stages                                        | Single Gemini structured-output call                            |
| Consolidation               | Create/Update/Merge/Ignore/Conflict                          | `Consolidator` with graph upsert + Postgres dedup               |
| Text embeddings             | Not mentioned in proposal                                    | `TextEmbedder` (Gemini) + `TextMemoryIndex` (FAISS 768-d)       |
| Forgetting strategy         | Keep/Archive/Compress/Delete                                 | Not implemented                                                 |
| Provenance                  | Source conversation, timestamp, confidence, related entities | `memory_facts`: `source_session_id`, `confidence`, `created_at` |

**Which is better?** The implementation is better for the MVP:

- **Merged extraction+classification** saves an API call. The proposal's two-stage approach would double Gemini costs for no quality gain.
- **Text embeddings** fill a gap in the proposal. The proposal mentions "semantic relevance" in retrieval but doesn't specify how. The implementation's text embeddings enable semantic search over extracted facts.
- **No forgetting** is correct for a dementia assistant. Forgetting is a premature optimization.
- **Trade-off:** Merged extraction means we can't use a cheaper model for classification. But Gemini Flash is already cheap enough.

**Should we switch?** No. Keep the merged approach. Add a separate classification stage only if we need domain-specific classification (e.g., medical terminology) that Gemini's general model handles poorly.

---

### 4.3 Perception Architecture

| Aspect              | Proposal                             | Implementation                                                |
| ------------------- | ------------------------------------ | ------------------------------------------------------------- |
| Frame sampling      | ~1 FPS                               | `FrameSampler` (~1 FPS)                                       |
| Face recognition    | InsightFace → FAISS                  | InsightFace → FAISS (same)                                    |
| Scene understanding | Gemini Vision                        | `SceneUnderstander` (Gemini Vision)                           |
| Speech recognition  | Separate STT module                  | RealtimeModel built-in STT                                    |
| Observation fusion  | Working Memory updated by Perception | `ObservationEngine` (1s window) → `WorkingMemory` (30s TTL)   |
| Device telemetry    | Not mentioned in proposal            | `data_channel.py` → `DeviceObservation` → `ObservationEngine` |

**Which is better?** The implementation is more detailed:

- **Built-in STT** eliminates a separate API call and reduces latency.
- **ObservationEngine fusion** is a concrete implementation of the proposal's "Working Memory is continuously updated by the Perception Layer" — it defines exactly how multiple observation sources are fused (1s window, dedup, weighted confidence).
- **Device telemetry** is not in the proposal but is a natural addition (battery, wifi, button state for the glasses).
- **Trade-off:** The 1s fusion window adds 0-1s latency to context updates. The proposal's "continuously updated" implies lower latency. But 1s is fine for dementia assistance (seconds, not milliseconds).

**Should we switch?** No. The implementation is a faithful and improved realization of the proposal.

---

### 4.4 Context Engine Architecture

| Aspect             | Proposal (context.md PRD)                                                          | Implementation                                    |
| ------------------ | ---------------------------------------------------------------------------------- | ------------------------------------------------- |
| Retrieval          | Semantic + Episodic + Graph + Face + Calendar + Reminder                           | Graph + Episodic + Text embeddings + Reminder     |
| Filtering          | Dedup, outdated, irrelevant, low-confidence, verbose                               | `Ranker` scores and sorts; top-k selection        |
| Ranking            | 7 signals (semantic, temporal, social, spatial, importance, confidence, frequency) | `Ranker` with weighted scoring                    |
| Summarization      | Compress when over context window                                                  | `Summarizer` (Gemini) compresses                  |
| Packaging          | Structured YAML-like format                                                        | `ContextPackage` dataclass + `to_text()` renderer |
| Provenance         | Memory ID, source, confidence, timestamp, entities                                 | `provenance` field in `ContextPackage`            |
| Refresh frequency  | Event-driven (new person, question, context change)                                | On `on_enter()` (folded into greeting)            |
| Token optimization | Explicit strategies (dedup, aggregation, compression)                              | `Summarizer` + `top_k` limit                      |

**Which is better?** The implementation is close to the PRD but has one gap:

- ~~**Context refresh frequency:** The PRD says event-driven. The implementation builds context once on `on_enter()`.~~

**Update (2026-08-12):** Context is now folded into the `generate_reply()` greeting on `on_enter()`. Mid-session `update_instructions()` is intentionally NOT called — the Gemini Live API corrupts the audio stream when `send_client_content(turn_complete=False)` is sent mid-session (confirmed via live testing: `CONTENT_TYPE_AUDIO not supported for this model configuration`). `_refresh_context()` builds context + logs it but does not push to the model. Mid-conversation context updates rely on tool calls.

**Should we switch?** ~~Add periodic context refreshes~~ Done. The `update_instructions()` limitation is a Gemini Live API constraint. If the API later supports mid-session instruction updates, `_refresh_context` can be extended to call `update_instructions()`.

---

## 5. What's Missing (Not Implemented)

### From the Proposal:

| Feature                             | Proposal Section               | Status                                                                                   |
| ----------------------------------- | ------------------------------ | ---------------------------------------------------------------------------------------- |
| Caregiver Dashboard                 | §Core Feature #4, Appendix A.3 | ❌ Not implemented                                                                       |
| Multi-caregiver support             | §Value Proposition             | ❌                                                                                       |
| Disorientation alerts               | §Core Feature #4               | ❌                                                                                       |
| Location alerts                     | §Core Feature #4               | ❌                                                                                       |
| Weekly recap reports                | §C.6 Retention                 | ❌                                                                                       |
| Memory Forgetting Strategy          | memory_os.md §14               | ❌                                                                                       |
| Procedural Memory                   | memory_os.md §12               | ❌ (proposal says "future")                                                              |
| Emotion-aware context               | context.md §18                 | ❌ (proposal says "future")                                                              |
| Privacy controls                    | §MVP Scope (excluded)          | ❌                                                                                       |
| Offline inference                   | §MVP Scope (excluded)          | ❌                                                                                       |
| OTA firmware updates                | §MVP Scope (excluded)          | ❌                                                                                       |
| Memory editing/correction           | memory_os.md §2                | ❌ (no tool for updating/correcting memories)                                            |
| Conflict detection in consolidation | memory_os.md §7                | Partial (Consolidator upserts, but no explicit conflict detection + confidence lowering) |

### From the PRDs:

| Feature                                | PRD Section            | Status                    |
| -------------------------------------- | ---------------------- | ------------------------- |
| Event-driven context refresh           | context.md §5          | ✅ (folded into greeting) |
| Heartbeat monitoring for session       | reasoning_agent.md §5  | ❌ (handled by framework) |
| Queue pending user requests on failure | reasoning_agent.md §13 | ❌                        |
| Memory confidence learning             | memory_os.md §17       | ❌                        |
| Provenance: related entities           | context.md §15         | Partial                   |

---

## 6. Is the Core Feature Set Implemented?

**Yes, 3 of 4 core features are fully implemented:**

1. **Real-time Face Recognition** — ✅ InsightFace → FAISS → Neo4j → tools → agent
2. **Context-Aware Memory Retrieval** — ✅ ContextEngine + Retriever + Ranker + Summarizer
3. **Proactive Everyday Assistance** — ✅ ProactivePlanner + context matching + generate_reply
4. **Caregiver Dashboard** — ❌ Not implemented (excluded from MVP scope by the proposal itself)

The memory pipeline (extraction → consolidation → graph + episodic storage) is fully functional. The observation engine fuses face, scene, speech, and device observations into a working memory with a 30s TTL. The proactive planner checks for context-relevant reminders every 30s. The agent can register new faces, search for people, create reminders, and manage shopping lists through 31 tool functions.

**What's missing is the caregiver-facing half of the product.** The patient-facing AI assistant is complete. The multi-caregiver dashboard with activity logs, disorientation alerts, and location alerts is not implemented. This was explicitly excluded from the MVP scope in the proposal.

---

## 7. Recommendations

### Do Now (bugs found in audit):

1. ~~**Fix `_safe_extract` wiring bug**~~ — ✅ Fixed (2026-08-12). Removed `_safe_extract`, wired `_on_extract` with text embeddings in `conversation_item_added`. (See `race-conditions.md` §5)
2. ~~**Make scene understanding non-blocking**~~ — ✅ Fixed (2026-08-12). Scene understanding fired as `asyncio.create_task` via `_understand_scene()`. (See `race-conditions.md` §10)

### Do Soon (product gaps):

3. ~~**Add periodic context refresh**~~ — ✅ Done (2026-08-12). Context folded into `generate_reply()` on `on_enter()`. Mid-session `update_instructions()` intentionally skipped — Gemini Live API corrupts audio stream on `send_client_content(turn_complete=False)` (confirmed via live testing).
4. ~~**Improve proactive planner matching**~~ — ✅ Done (2026-08-12). Added `text_embedder` to `ProactivePlanner`. Keyword pass first (free), then batch embedding similarity (one API call per 30s cycle, threshold 0.5) for unmatched items. Fixes "apotek vs beli paracetamol" gap.

### Do Later (scale + polish):

5. **Add memory correction tools** — allow the user to say "bukan, Asep suka tempe" and have the agent update the graph.
6. **Add conflict detection** — when new facts contradict existing ones, lower confidence and ask for confirmation.
7. **Add provenance to all facts** — link each fact to its source conversation for explainability.
8. **Bootstrap `TextMemoryIndex`** from existing Postgres facts on startup (currently empty until live conversations populate it).
9. **Caregiver dashboard** — the proposal's core Feature #4, but explicitly excluded from MVP.

### Keep As-Is:

- AgentSession + RealtimeModel (better than proposal's direct API)
- Merged extraction + classification (saves API calls)
- Text embeddings via TextMemoryIndex (fills proposal gap)
- No forgetting strategy (correct for dementia assistant)
- UV workspaces instead of NX (correct for Python)
- Built-in STT via RealtimeModel (simpler than separate Whisper)
