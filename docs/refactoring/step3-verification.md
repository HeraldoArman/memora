# Step 3: Scene Understanding — Verification

**Branch:** `refactor/agent-session-gemini`
**Date:** 2026-08-12
**Result:** ✅ Unit tests pass (400/400), lint clean, live verification pending

---

## What Was Done

Wire the SceneUnderstander into the video loop so the agent knows where it is.
"Dimana aku?" → agent calls `current_scene` → returns location from Gemini Vision
analysis.

### Memory leak — not an issue on new architecture

The original ~100MB/min leak was from the old custom WebSocket architecture (frequent
2s calls + `np.frombuffer` view keeping LiveKit buffers alive + `model_dump` serializing
full image bytes). Research on the current `google-genai` 2.17.0:

- **#2235** (image-input `model_dump` leak): **fixed** in our version (PR #2236 merged
  Apr 2026). Our `pyproject.toml` pins `google-genai==2.17.0`.
- **#2369** (image-output response retention): only affects image _generation_ (~3.4MB
  per response). Scene understanding sends JPEG as input and gets small JSON back —
  negligible retention.
- **#1258** (streaming leak): we use non-streaming `generate_content`, not affected.
- **Client reuse is correct**: one `genai.Client` reused across calls is the intended
  pattern. Per-call construction would discard connection pooling + leak aiohttp sessions.
- The sampler's `.copy()` fix (breaking `np.frombuffer` view) already resolved the
  buffer retention issue from the bare-minimum refactor.

**No leak fix needed.** The SceneUnderstander's existing client-reuse pattern is safe.

### Files changed

| File                               | Change                                                                                                               |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `tools/registry.py`                | Added `last_scene: dict \| None = None` to `ToolContext`                                                             |
| `tools/observation/tools.py`       | `current_scene` + `current_activity` read from `ctx.last_scene`                                                      |
| `gateway/livekit/entrypoint.py`    | Instantiate `SceneUnderstander`, pass to `handle_video_track`                                                        |
| `gateway/livekit/track_handler.py` | Accept `scene_understander` param, call every 5 frames → `tool_ctx.last_scene`                                       |
| `tests/unit/test_tools.py`         | 4 new tests: `current_scene` available/no-location, `current_activity` available/unavailable                         |
| `tests/unit/test_gateway.py`       | 3 new tests: `_encode_jpeg` valid/failure, `last_scene` defaults                                                     |
| `tests/unit/test_reasoning.py`     | 4 new Step 2 tests: context build exception, last_face → visible_people, no-face empty visible, graceful degradation |

### Diff size

~40 lines production code, ~60 lines test code.

---

## How It Works

```
Video frame (every 1s at 1 FPS)
  → FrameSampler → bgr numpy array
  → FaceRecognizer → tool_ctx.last_face (unchanged)
  → Every 5th frame (~5s):
    → _encode_jpeg(bgr) → JPEG bytes
    → SceneUnderstander.understand(jpeg)
      → genai.Client.aio.models.generate_content(
          model=gemini-flash-latest,
          contents=[JPEG, SCENE_PROMPT],
          config=response_mime_type=application/json + response_schema=SCENE_SCHEMA
        )
      → _parse(resp) → _normalize(data)
      → {"location": "apotek", "objects": ["obat"], "activity": "beli obat", "confidence": 0.9}
    → tool_ctx.last_scene = result

Agent tool call: current_scene
  → tools.observation.tools.current_scene({}, ctx)
  → ctx.last_scene = {"location": "apotek", ...}
  → {"available": True, "location": "apotek", "objects": ["obat"], "activity": "beli obat"}

Agent tool call: current_activity
  → tools.observation.tools.current_activity({}, ctx)
  → ctx.last_scene = {"location": "apotek", "activity": "beli obat", ...}
  → {"available": True, "activity": "beli obat", "location": "apotek"}
```

### Key design decisions

1. **Every 5 frames (~5s), not every frame:** Gemini Vision API calls are expensive
   (~1-2s latency). At 1 FPS, every 5th frame = every 5s. Scene doesn't change fast —
   a pharmacy doesn't become a kitchen in 5s. Matches the PRD's event-driven reasoning
   strategy (§5: "LLM activated on contextual changes, not every frame").

2. **Direct dict to `tool_ctx.last_scene`:** Same pattern as `last_face` — no
   ObservationEngine, no WorkingMemory, no fusion window. The video loop writes
   directly. Tools read directly. Simple, deterministic, no race conditions.

3. **Graceful degradation:** SceneUnderstander failure (API down, bad JPEG, parse
   error) → `last_scene` stays at previous value or None. `current_scene` tool
   returns `{"available": False}`. Agent still works — just doesn't know location.

4. **`_encode_jpeg` in track_handler:** Reuses the existing `_encode_jpeg` from
   `sampler.py` (which has a self-check). Wrapped in try/except to never crash the
   video loop.

5. **No ObservationEngine (Step 5):** Scene results go directly to `tool_ctx.last_scene`
   dict. The ObservationEngine fusion window (1s dedup, 30s TTL) is architecturally
   cleaner but not needed for a single-sensor demo. Re-enable in Step 5 if multi-sensor
   fusion is needed.

---

## Test Results

```
400 passed, 0 failed, 2 warnings in 16.15s
ruff check . → All checks passed!
ruff format --check . → 114 files already formatted
```

### New tests added (Step 3)

| Test                               | Verifies                                                            |
| ---------------------------------- | ------------------------------------------------------------------- |
| `test_current_scene_available`     | `current_scene` returns location/objects/activity from `last_scene` |
| `test_current_scene_no_location`   | `current_scene` returns unavailable when location is None           |
| `test_current_activity_available`  | `current_activity` returns activity/location from `last_scene`      |
| `test_encode_jpeg_valid`           | `_encode_jpeg` produces non-empty JPEG bytes                        |
| `test_encode_jpeg_none_on_failure` | `_encode_jpeg` returns None on invalid input (no crash)             |
| `test_last_scene_defaults_none`    | `ToolContext.last_scene` defaults to None                           |
| `test_last_scene_set`              | `ToolContext.last_scene` can be set and read                        |

### New tests added (Step 2 additional)

| Test                                          | Verifies                                                            |
| --------------------------------------------- | ------------------------------------------------------------------- |
| `test_on_enter_context_build_exception`       | ContextEngine.build() exception → keeps static prompt, still greets |
| `test_on_enter_builds_context_from_last_face` | `on_enter` passes `visible_people=["Asep"]` to ContextEngine.build` |
| `test_on_enter_no_face_empty_visible`         | No face → `visible_people=[]` passed to ContextEngine.build`        |

### Updated tests

| Test                                | Was testing                           | Now testing                                |
| ----------------------------------- | ------------------------------------- | ------------------------------------------ |
| `test_current_scene_unavailable`    | Always returns unavailable (bare-min) | Returns unavailable when `last_scene=None` |
| `test_current_activity_unavailable` | Always returns unavailable (bare-min) | Returns unavailable when `last_scene=None` |

---

## Live Verification (pending)

### Test plan

1. Ensure Step 1 data exists (Person:Asep in Neo4j, facts in Postgres)
2. Start worker (with Postgres + Neo4j running)
3. Publish a video track with a recognizable scene (e.g. kitchen, pharmacy)
4. Wait ~5s for scene understanding to run (every 5 frames at 1 FPS)
5. Send prompt: "dimana aku?" via data channel
6. Agent should call `current_scene` → returns location from `last_scene`
7. Agent responds: "Anda di dapur" (or similar)
8. Check worker log: `scene understood: location=dapur activity=memasak confidence=0.85`
9. Monitor memory: should stay stable for 5+ minutes

### Step 2 live verification (also pending)

1. Start worker (with Postgres + Neo4j running)
2. Send prompt: "siapa Asep?" via data channel
3. Agent should answer from injected system prompt (no tool call needed)
4. Check worker log: `on_enter: update_instructions with N chars context`

### What to look for in logs

**Step 3:**

```
scene understander created
video loop started — sampling frames for InsightFace + scene understanding
scene understood: location=apotek activity=beli obat confidence=0.90
tool call: current_scene args={}
tool result: current_scene → {'available': True, 'location': 'apotek', ...}
```

**Step 2:**

```
on_enter: agent becoming active
on_enter: update_instructions with 250 chars context
on_enter: greeting generated
```

---

## What's Next

Step 4: Proactive Planner — agent proactively reminds user about pending tasks when
context matches. Entering a pharmacy → "Jangan lupa beli paracetamol." Depends on
Step 3 (scene understanding for location context).
