# Audio Latency — Event Loop Blocking in Video Loop

**Date:** 2026-08-12
**Status:** Suspect analysis (research only — no code changed)
**Symptom:** User speech logged ~15s after it was actually spoken. Tool calling is fast.

---

## Symptom

`logs/worker.log` shows user text `'Ini namanya cucuk.'` logged at `09:38:33`
(lines 170-172):

```
09:38:33 INFO entrypoint:201 — conversation_item_added: role=user text='Ini namanya cucuk.' interrupted=False
09:38:33 INFO entrypoint:219 — user turn detected, triggering extraction: 'Ini namanya cucuk.'
```

The user actually spoke it ~`09:38:15`–`09:38:20` — roughly 13-18s earlier. The log
timestamp is delayed relative to real speech ("the log also follow my input"). Tool
calls (`search_person`, `register_person`, `register_face`) all fire within the same
second they're invoked — fast and unaffected.

The previous turn shows the same pattern: `'Ini siapa ya?'` logged at `09:38:19`,
assistant replies at `09:38:27` ("Siapa ini?"), user says "Ini namanya cucuk." almost
immediately after (~`:28`-`:30`), but it isn't logged until `09:38:33`.

## Root Cause Hypothesis

The asyncio event loop (`MainThread`, pid=253445) is **blocked by synchronous work in
the video loop**, starving the AgentSession's audio-input processing path. Gemini Live
(`gemini-2.5-flash-native-audio-preview`) runs its own server-side VAD + endpointing. When
the client event loop can't feed/poll audio frames promptly (because it's busy doing
sync CPU work), the model's turn detection fires late → `conversation_item_added` fires
late → the log timestamp lags real speech.

Why tool calls are fast: tool dispatch is a short callback on the event loop between
turns. It doesn't depend on the continuous audio-stream polling path that gets starved.
The latency specifically hits the **audio input → server-side turn detection** path.

## Evidence

1. **Everything runs on one thread.** Every log line is `pid=253445 MainThread`. The
   AgentSession (Gemini audio) and the video loop (InsightFace) share the same asyncio
   event loop. Any sync work on that thread blocks both.

2. **Video frame cadence is 2s, not 1s — and has 5s stalls.** `frame_sample_fps=0.5`
   (intentional, `packages/config/env/settings.py:71` — InsightFace ONNX leaks ~20MB/
   frame on CPU, 1 FPS OOMs in 80s). Frames land at `:01,:02,:04,:05,:07,:09,:14...` —
   the `:09→:14` gap is a **5s stall** with no frame. That stall window is exactly when
   audio turn detection would be starved.

3. **`gc.collect()` runs on the event loop thread every 5 frames (~10s).**
   `track_handler.py:96-97`:

   ```python
   if frame_count % 5 == 0:
       gc.collect()
   ```

   Synchronous stop-the-world. `gc.collect()` on a multi-hundred-MB heap (InsightFace
   - ONNX + numpy + LiveKit buffers) can take hundreds of ms to over a second. Every
     occurrence freezes the event loop — including the audio pump — for that duration.

4. **`face_repo.lookup()` is sync and runs on the event loop thread.**
   `track_handler.py:123`:

   ```python
   result = face_repo.lookup(detected.embedding)
   ```

   `FaceRepository.lookup` (`packages/database/vector/repository.py:65`) is pure sync —
   `l2_normalize` + `index.search` (FAISS). Unlike `detect_and_embed` at line 56
   (which IS wrapped in `await asyncio.to_thread(...)`), the FAISS lookup is NOT
   offloaded. Per-frame numpy + FAISS work directly on the loop thread. Small per
   call, but it adds to every frame's blocking budget.

5. **`_recycle_app()` — ~4s ONNX model reload — contends for the GIL.**
   `perception/face/recognizer.py:72-91`: every 30 inference calls (~60s at 0.5 FPS) the
   ONNX session is torn down + rebuilt to flush the leak. It runs inside
   `detect_and_embed`, which IS on an executor thread (`asyncio.to_thread`). But the
   reload calls `gc.collect()` (line 88) + a ~4s model load, and CPython's GIL means a
   CPU-bound executor thread competes with the event loop thread for execution time.
   During the reload the `await asyncio.to_thread(...)` at line 56 also can't return,
   so the video loop (and thus any audio work co-scheduled on the loop) stalls until
   the reload finishes. This matches the `:09→:14` 5s gap.

6. **Memory warnings firing repeatedly.** `09:38:08`, `:16`, `:21` —
   `_memory_monitor_task()` on the supervisor (pid=253024) warns the job process is
   above threshold. High heap pressure → `gc.collect()` gets slower (more objects to
   trace) → longer event-loop freezes. Feedback loop: leak → pressure → slow GC →
   audio lag.

## Suspect Ranking (most → least impactful)

| #   | Suspect                           | Location                                                         | Why it blocks audio                                                                          | Severity                         |
| --- | --------------------------------- | ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | -------------------------------- |
| 1   | `gc.collect()` on event loop      | `track_handler.py:96-97`                                         | Direct STW on the loop thread every ~10s; freezes audio pump                                 | **High**                         |
| 2   | `_recycle_app()` 4s reload        | `recognizer.py:72-91` (via `to_thread` at `track_handler.py:56`) | GIL contention + `await` can't return until reload done; ~5s stall every 60s                 | **High**                         |
| 3   | `face_repo.lookup()` sync on loop | `track_handler.py:123` → `vector/repository.py:65`               | Per-frame sync FAISS+numpy on loop thread; not offloaded like `detect_and_embed`             | **Medium**                       |
| 4   | Heap pressure → slow GC           | (consequence of #1+#2)                                           | Bigger heap → each `gc.collect()` slower → longer freezes                                    | **Medium**                       |
| 5   | Video input token load to Gemini  | `entrypoint.py:319` `video_input=True`                           | Each frame tokenized inline by Gemini Live; heavy video may slow model-side audio processing | **Low (server-side, secondary)** |

## Why Tool Calling Is Fast

Tool calls fire from the AgentSession tool-call callback — a short, event-loop-bound
handler that runs _between_ turns. It doesn't depend on the continuous audio-stream
polling that gets starved by the video loop's sync work. Once a turn is detected (late),
the tool dispatch + result return is quick. The latency is front-loaded on the
_detection_ of the turn, not on tool execution after it.

## Recommended Fixes (not yet applied — "do not code yet")

1. **Remove `gc.collect()` from the event loop.** `track_handler.py:96-97`. The
   per-frame `del bgr, faces` already drops references; let Python's generational GC
   handle the rest. If a manual collection is truly needed for the ONNX leak, run it
   inside `_recycle_app()` on the executor thread (already done at `recognizer.py:88`)
   — don't duplicate it on the loop. **One-line delete. Biggest win.**

2. **Offload `face_repo.lookup()` to a thread.** `track_handler.py:123`:

   ```python
   result = await asyncio.to_thread(face_repo.lookup, detected.embedding)
   ```

   Matches the pattern already used for `detect_and_embed` at line 56. Stops per-frame
   sync FAISS/numpy work from touching the loop.

3. **Move `_recycle_app()` off the hot path.** Two options:
   - Run face detection in a **separate process** (the `settings.py:71` comment already
     names this as the fix). A dedicated face-worker process isolates the 4s reload +
     leak + GC from the audio event loop entirely. Biggest architectural win, most work.
   - Short-term: increase `_MAX_INFERENCE_CALLS` so recycles are rarer, and/or drop the
     0.5 FPS throttle back toward 1 FPS once the loop is unblocked (the throttle exists
     to survive the leak; if collection moves off-loop, pressure eases).

4. **Tune `frame_sample_fps` back up only after #1-#3 land.** The 0.5 FPS throttle is a
   symptom workaround (OOM avoidance). Once the loop isn't doing sync work + STW GC,
   memory behavior should be re-measured.

5. **(Separate bug, noted)** `text-embedding-004` returns 404 NOT_FOUND
   (`worker.log:209`). The embedding model is deprecated/unavailable — consolidator
   batch embed fails. Not the audio-latency cause, but breaks the text memory index.
   Switch to `text-embedding-001` or whatever the current Gemini embedding model is.

## What To Verify Before Coding

- Add `loop.run_in_executor` timing logs around `gc.collect()` and `face_repo.lookup()`
  to confirm the actual STW durations on this heap.
- Confirm whether Gemini Live's turn detection is client-fed (VAD on client) or purely
  server-side. If client-side VAD: blocked event loop → delayed VAD events → exactly
  this symptom. If server-side: client must still pump audio frames up promptly; a
  stalled loop delays the pump. Either way the loop-block hypothesis holds, but the
  mechanism differs. Check LiveKit `google.realtime` plugin source for VAD handling.
- Measure: with `gc.collect()` removed, does the `:09→:14` 5s gap disappear? That gap
  is the cleanest single signal of a loop stall.

## References

- `logs/worker.log` lines 90-213 — the symptom window (frames 4-21, the `:09→:14` stall,
  the delayed `:33` turn).
- `apps/backend/gateway/livekit/track_handler.py:56,96-97,123` — the three block points.
- `apps/backend/perception/face/recognizer.py:72-91` — `_recycle_app()` 4s reload.
- `packages/config/env/settings.py:68-71` — 0.5 FPS throttle rationale (ONNX leak).
- `packages/database/vector/repository.py:65` — sync `lookup()`.
- `docs/audit/race-conditions.md` #10 — prior scene-understanding block (already fixed
  via `asyncio.create_task`, the model for fix #1-#2 above).
- LiveKit docs: `video_input=True` streams frames inline with the Gemini realtime audio
  session; each frame is tokenized server-side. (docs/agents/models/realtime/plugins
  /gemini + docs/agents/multimodality/vision/video)
