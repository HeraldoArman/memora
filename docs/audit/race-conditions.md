# Race Condition & Concurrency Audit

**Scope:** `refactor/agent-session-gemini` branch, Steps 1–5 (all modified files).
**Date:** 2026-08-12
**Severity scale:** P0 (data loss/crash) → P1 (wrong behavior, recoverable) → P2 (benign, fix when noticed)

---

## 1. ToolContext Shared Mutable State — No Synchronization

**Severity:** P1

**Where:** `tools/registry.py:56-65`, `gateway/livekit/track_handler.py:75,84,172-179`, `reasoning/agent/agent.py:105-131`

`ToolContext` holds `last_face`, `last_scene`, `working_memory`, `_last_unknown_embedding`, and `_unknown_embedding_deadline` as plain instance attributes. These are read and written from multiple concurrent asyncio tasks:

- **Writer:** `handle_video_track._video_loop()` — runs as `asyncio.create_task`. Writes `tool_ctx.last_face` (line 75, 172-179), `tool_ctx.last_scene` (line 84), `tool_ctx._last_unknown_embedding` via `cache_unknown_embedding()`.
- **Reader:** `MemoraAgent._get_context()` — called by the proactive planner's 30s loop and by `on_enter()`. Reads `tool_ctx.last_face`, `tool_ctx.last_scene`.
- **Reader:** `MemoraAgent._build_context_text()` — called from `on_enter()`. Reads `tool_ctx.last_face`.
- **Reader:** Tool dispatch (`_dispatch._handler`) — runs inside the AgentSession's tool-call callback. Reads `tool_ctx.last_face`, `tool_ctx.last_scene`, `tool_ctx.current_face_embedding()`.

**The race:** In CPython, asyncio tasks switch at `await` points, not between every statement. So a read of `self.last_face` that doesn't cross an `await` is atomic at the bytecode level. But `_get_context()` reads `self._tool_ctx.last_face` then `self._tool_ctx.last_scene` — between these two reads (no `await`), the video loop could write to both, so you get a face from frame N and a scene from frame N+5. This is a **torn read**: the face and scene come from different moments.

**Impact:** The agent might say "You're at the pharmacy" (scene from frame 10) while the face data is from the supermarket (frame 5). Low probability — scene updates every 5 frames, face updates every frame — but possible during rapid context transitions.

**Mitigation (lazy):** Since asyncio is cooperative (no preemption between non-`await` lines), the torn read window is the 2-3 lines between reading `last_face` and `last_scene` in `_get_context()`. This window has zero `await` calls, so it can only be interrupted by signal handlers or GC. **In practice this is safe under CPython.** A proper fix would snapshot both into a local var:

```python
def _get_context(self):
    face = self._tool_ctx.last_face
    scene = self._tool_ctx.last_scene
    # ... use face, scene
```

We already do this in the fallback path. The `working_memory.get()` path returns an immutable `CurrentContext` (set once by the engine), so it's torn-read-free.

**Verdict:** Acceptable for current scale. Fix if we move to threading or multi-worker.

---

## 2. ObservationEngine Queue — Fire-and-Forget `asyncio.create_task` for Emissions

**Severity:** P2

**Where:** `gateway/livekit/entrypoint.py:176-180`

```python
@session.on("user_input_transcribed")
def _on_transcribed(ev):
    ...
    asyncio.create_task(obs_engine.emit(SpeechObservation(...)))
```

The `emit()` call is fire-and-forget. If the task raises an exception (e.g., queue full — though `asyncio.Queue` is unbounded by default), the exception is swallowed by the event loop's exception handler and logged as "Task exception was never retrieved." No data loss, but the observation is lost.

Similarly, `track_handler.py:194` calls `await obs_engine.emit(FaceObservation(...))` directly (not fire-and-forget), so that path is safe.

**Impact:** A missed SpeechObservation means the proactive planner's "Siapa ini?" trigger won't fire for that utterance. The planner runs every 30s, so the next utterance will trigger it. Low impact.

**Verdict:** Acceptable. The queue is unbounded, so the only failure mode is OOM from a stuck consumer — which would crash the worker anyway.

---

## 3. ObservationEngine Start Order — Observations Emitted Before Engine Starts

**Severity:** P1

**Where:** `gateway/livekit/entrypoint.py:309`

```python
await session.start(...)
obs_engine.start()  # ← started AFTER session
```

Between `session.start()` and `obs_engine.start()`, the following events can fire:

- `user_input_transcribed` — the user could speak immediately after the agent greets them
- `track_subscribed` — video frames start arriving, `handle_video_track` is spawned, which calls `obs_engine.emit(FaceObservation(...))`
- `data_received` — device telemetry could arrive

All of these `await obs_engine.emit(...)` calls. `emit()` does `await self.queue.put(observation)` on an `asyncio.Queue`. The queue is created in `__init__` (before `start()`), so `put()` works even before the consumer task starts. The observations sit in the queue and are drained when `_run()` starts.

**But:** The `_run()` loop calls `self._collect_window()` which starts with `await self.queue.get()` — this blocks until the first item arrives. If items were already queued before `start()`, the first `get()` returns immediately, but the fusion window deadline is computed from `asyncio.get_event_loop().time()` after the first `get()`. This means pre-started observations get a full fusion window, not the remaining time. This is fine — it's just a slightly larger first window.

**Verdict:** Safe. Queue-based decoupling handles this correctly. No fix needed.

---

## 4. ProactivePlanner vs AgentSession — `generate_reply` from a Background Task

**Severity:** P1

**Where:** `reasoning/planner/planner.py:156-167`, `reasoning/agent/agent.py:133-136`

The planner runs as an `asyncio.create_task` with a 30s sleep loop. When it finds a match, it calls `await on_trigger(prompt)` which calls `await self.session.generate_reply(instructions=text)`.

**The race:** `generate_reply` is a LiveKit AgentSession method. If the user is mid-conversation (the model is generating a response), calling `generate_reply` concurrently could:

1. Interrupt the in-progress response (acceptable — proactive reminders should interrupt).
2. Raise a concurrency error if the session doesn't support concurrent `generate_reply` calls.
3. Queue internally and execute after the current response finishes (delayed but safe).

**What actually happens:** LiveKit's `AgentSession.generate_reply` is designed to be called from any context — it sends an instruction to the model. If the model is mid-response, it interrupts (similar to barge-in). This is the desired behavior for proactive reminders.

**Verdict:** Safe by design. The interruption is a feature, not a bug.

---

## 5. `_safe_extract` vs `conversation_item_added` — Double Extraction

**Severity:** P2

**Where:** `gateway/livekit/entrypoint.py:114-120` (`_on_extract`), `entrypoint.py:328-337` (`_safe_extract`), `entrypoint.py:183-214` (`_on_conversation_item`)

The `_on_extract` callback (passed to `MemoraAgent`) and `_safe_extract` (called from `conversation_item_added`) both run the extraction pipeline. Let's trace the call paths:

1. `MemoraAgent.__init__` receives `on_extract=_on_extract` (the entrypoint closure).
2. `conversation_item_added` handler checks `if item.role == "user"` and calls `asyncio.create_task(_safe_extract(text, session_id))`.
3. `_on_extract` is never actually called by `MemoraAgent` — the old `on_user_turn_completed` hook was removed in the AgentSession refactor. The `conversation_item_added` event replaced it.

**Wait — is `_on_extract` dead code?** Let's check: `agent._on_extract` is checked in `conversation_item_added` (`if text and agent._on_extract:`), but `_safe_extract` is called regardless of whether `agent._on_extract` is set. And `_on_extract` itself is the one that creates a `PipelineRunner` with `text_embedder` + `text_index`, while `_safe_extract` creates a bare `PipelineRunner()`.

**This means:** Every user message triggers `_safe_extract` (bare runner, no text embeddings), and `_on_extract` is never called (it's only checked as a truthy gate). The text embeddings from Step 2 are NOT being used during extraction — they're only used by the ContextEngine's retriever.

**Impact:** The `TextMemoryIndex` never gets populated from live conversations. It only works if someone manually runs `pipeline/runner.py --verify`. The ContextEngine's retrieval will return empty results from the text index, falling back to graph-only retrieval.

**Fix:** Replace `_safe_extract` call with `_on_extract` call in `conversation_item_added`, or pass `text_embedder` + `text_index` to `_safe_extract`.

**Verdict:** P1 bug. Not a race condition, but a wiring bug that defeats Step 2's text index. Fix immediately.

---

## 6. `build_registry()` Module-Level Singleton — Lazy Global State

**Severity:** P2

**Where:** `tools/registry.py:128-153`

`_REGISTRY` is a module-level dict, populated lazily on first call to `build_registry()`. In the AgentSession architecture, `build_registry()` is called inside `_dispatch()`, which is called for each tool declaration at agent construction time.

**The race:** If two rooms (two `entrypoint()` calls) run in the same process, `build_registry()` is called twice concurrently. The first call sets `_REGISTRY`, the second sees it's not None and returns the cached version. Since there's no `await` between the `if _REGISTRY is not None` check and the population of `_REGISTRY`, this is atomic under asyncio.

**But:** The registry contains tool callables that close over `ToolContext` — wait, no. `build_registry()` returns a dict of `ToolFunc` callables that take `(args, ctx)` as parameters. The `ctx` is passed at call time, not closed over. So the singleton is safe — it's just a dispatch table.

**Verdict:** Safe. No fix needed.

---

## 7. FaceRecognizer ONNX Session — Thread Safety of `_recycle_app()`

**Severity:** P1

**Where:** `perception/face/recognizer.py` (not modified, but called from `track_handler.py:53`)

`recognizer.detect_and_embed(bgr)` is called via `await asyncio.to_thread(...)`, which runs it in a thread pool executor. The ONNX session is not thread-safe — if two video tracks subscribe simultaneously (two participants), two threads could call `detect_and_embed` at the same time on the same ONNX session.

**Mitigation already in place:** The recognizer recycles the ONNX session every 30 calls via `_recycle_app()`. But the recycling itself is not synchronized — if thread A is mid-inference and thread B calls `_recycle_app()`, A's session object could be replaced mid-inference.

**Impact:** ONNX inference on a stale/replaced session could crash or return garbage. In practice, the ESP32-S3 prototype has a single camera, so there's only one video track. This is a theoretical race.

**Verdict:** Safe for single-participant rooms. Add a `threading.Lock` around `detect_and_embed` + `_recycle_app` if multi-participant support is needed.

---

## 8. WorkingMemory TTL — Stale Context Used for Tool Calls

**Severity:** P2

**Where:** `perception/observation/working_memory.py:29-34`, `tools/registry.py:110-124`

`WorkingMemory.get()` returns `None` if the context is older than 30s. But `device_snapshot()` in `ToolContext` calls `self.working_memory.get()` and, if it returns None, falls back to `{}`. This means the agent gets an empty device snapshot if no telemetry has been received in the last 30s.

**The race:** Device telemetry arrives every 10s (say). The ObservationEngine fuses it into a `CurrentContext` and calls `working_memory.set()`. The 30s TTL is from the last `set()`. If the agent calls `device_snapshot()` 31s after the last telemetry, it gets `{}` even though the device is still at 72% battery.

**Impact:** The agent says "I don't know the battery level" instead of "72%". Low impact — the user can ask again, and the next telemetry packet will refresh the context.

**Verdict:** Acceptable. The TTL is a feature (stale data is worse than no data). If we want longer-lived device data, we can separate device telemetry from the 30s context TTL.

---

## 9. `conversation_item_added` — Extraction Fires on Every User Message, No Dedup

**Severity:** P2

**Where:** `gateway/livekit/entrypoint.py:206-210`

```python
if item.role == "user":
    text = item.text_content or ""
    if text and agent._on_extract:
        asyncio.create_task(_safe_extract(text, session_id))
```

If the same user message is delivered twice (LiveKit retry, network glitch), extraction fires twice. The `PipelineRunner` will call `KnowledgeExtractor.extract()` twice, and `Consolidator.consolidate()` will try to insert the same facts twice.

**Mitigation:** The Consolidator's dedup logic (comparing against existing knowledge before inserting) should handle this — that's its job. But it adds unnecessary API calls to Gemini for the duplicate extraction.

**Verdict:** Low impact. The Consolidator handles it. Add a message-ID dedup cache if Gemini API costs become a concern.

---

## 10. Scene Understanding — Blocking Gemini Vision Call in Video Loop

**Severity:** P1

**Where:** `gateway/livekit/track_handler.py:82`

```python
scene = await scene_understander.understand(jpeg)
```

This is an `await` inside the video loop. While the Gemini Vision API call is in flight (100-500ms), the video loop is blocked — no face detection happens. If the SceneUnderstander call takes longer than 1 frame interval (1s at 1 FPS), frames are dropped.

**Impact:** Face recognition pauses every 5 frames for the duration of the scene understanding call. If Gemini Vision takes 500ms, face recognition has a 500ms gap every 5s. A person walking by during that gap could be missed.

**Fix:** Run `scene_understander.understand(jpeg)` in a separate task:

```python
if frame_count % 5 == 0:
    jpeg = _encode_jpeg(bgr)
    if jpeg:
        asyncio.create_task(_understand_scene(jpeg, tool_ctx, obs_engine))
```

**Verdict:** P1 — fix this. Face recognition should never block on scene understanding.

---

## Summary Table

| #   | Issue                                                     | Severity   | Fix?                            |
| --- | --------------------------------------------------------- | ---------- | ------------------------------- |
| 1   | ToolContext torn reads (face+scene from different frames) | P1         | No (asyncio-safe under CPython) |
| 2   | Fire-and-forget `obs_engine.emit` for SpeechObservation   | P2         | No (unbounded queue)            |
| 3   | Observations emitted before engine starts                 | P1         | No (queue handles it)           |
| 4   | Planner `generate_reply` concurrent with user speech      | P1         | No (interruption is desired)    |
| 5   | `_safe_extract` doesn't use text_embedder/text_index      | **P1 bug** | **Yes — fix now**               |
| 6   | `build_registry()` lazy singleton                         | P2         | No (asyncio-safe)               |
| 7   | ONNX session not thread-safe for multi-participant        | P1         | No (single-participant only)    |
| 8   | WorkingMemory 30s TTL on device data                      | P2         | No (by design)                  |
| 9   | Double extraction on duplicate messages                   | P2         | No (Consolidator dedups)        |
| 10  | Scene understanding blocks face recognition               | P1         | **Yes — fix when noticed**      |

## Immediate Fixes

### Fix 5: Wire `_on_extract` instead of `_safe_extract`

In `entrypoint.py:conversation_item_added`, replace `_safe_extract` with `_on_extract` so the text embedder + index are used:

```python
# Before:
asyncio.create_task(_safe_extract(text, session_id))

# After:
asyncio.create_task(_on_extract(text, session_id))
```

Or better, remove `_safe_extract` entirely and add error handling to `_on_extract`.

### Fix 10: Non-blocking scene understanding

In `track_handler.py`, fire scene understanding as a separate task so face recognition never blocks:

```python
if scene_understander is not None and frame_count % 5 == 0:
    jpeg = _encode_jpeg(bgr)
    if jpeg:
        asyncio.create_task(_understand_scene_async(jpeg, tool_ctx, scene_understander, obs_engine))
```

Both fixes are <10 lines each.
