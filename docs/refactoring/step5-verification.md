# Step 5 Verification — Observation Engine + Working Memory

**Branch:** `refactor/agent-session-gemini`
**Date:** 2026-08-12

---

## What was wired

The `ObservationEngine` + `WorkingMemory` were already fully implemented with
tests. Step 5 wires them into the live agent lifecycle, additive to the existing
`last_face`/`last_scene` dict pattern:

1. **`gateway/livekit/entrypoint.py`**: Instantiate `WorkingMemory` +
   `ObservationEngine`. Set `tool_ctx.working_memory`. Start engine after
   `AgentSession.start()`, stop in `finally` block. Wire `user_input_transcribed`
   event → `SpeechObservation` (final only). Wire device data channel topic →
   `handle_data_received` → `DeviceObservation`.

2. **`gateway/livekit/track_handler.py`**: Accept `obs_engine` param.
   `_update_last_face` emits `FaceObservation` after writing to `tool_ctx.last_face`.
   Scene understanding emits `SceneObservation` after writing to `tool_ctx.last_scene`.

3. **`tools/registry.py`**: Added `working_memory: Any = None` to `ToolContext`.
   `device_snapshot()` reads `DeviceObservation` from working_memory when available,
   falls back to `{}`.

4. **`reasoning/agent/agent.py`**: `_get_context()` and `_build_context_text()`
   prefer `working_memory.get()` (fused `CurrentContext` with speech + device + TTL),
   fall back to `last_face`/`last_scene` dicts when working_memory is None or expired.

### Design decisions

- **Additive, not replacement**: `last_face` and `last_scene` dicts stay on
  `ToolContext`. Tools that read them (`visible_people`, `current_scene`,
  `current_activity`, `current_face_embedding`) keep working unchanged. The
  observation engine runs in parallel and provides a richer `CurrentContext`.

- **No speech suppression needed**: `user_input_transcribed` is user-mic-only
  STT. The agent's own speech never triggers this event. No need to check
  `agent_state` before emitting `SpeechObservation`.

- **Final transcripts only**: `is_final=False` (interim) transcripts are skipped.
  Only `is_final=True` with non-empty text emits a `SpeechObservation`.

- **Device data channel wired**: The "device" topic now calls
  `handle_data_received()` from `data_channel.py` (already implemented, just
  wasn't wired). Parses JSON → `DeviceObservation` → `obs_engine.emit()`.

---

## Files changed

| File                                            | Change                                                                            |
| ----------------------------------------------- | --------------------------------------------------------------------------------- |
| `apps/backend/gateway/livekit/entrypoint.py`    | Instantiate WorkingMemory + ObsEngine, wire speech + device, start/stop lifecycle |
| `apps/backend/gateway/livekit/track_handler.py` | `obs_engine` param, emit FaceObservation + SceneObservation                       |
| `apps/backend/tools/registry.py`                | `working_memory` field, `device_snapshot()` reads from working_memory             |
| `apps/backend/reasoning/agent/agent.py`         | `_get_context()` + `_build_context_text()` prefer working_memory                  |
| `apps/backend/tests/unit/test_gateway.py`       | 3 new tests for FaceObservation emission                                          |
| `apps/backend/tests/unit/test_reasoning.py`     | 5 new tests for working_memory preference + fallback                              |
| `apps/backend/tests/unit/test_tools.py`         | 3 new tests for device_snapshot from working_memory                               |

## Diff size

~72 lines production, ~85 lines test

---

## Test results

```
353 passed, 1 warning in 6.75s
```

All tests pass, lint clean.

### New tests (11)

| Test                                             | What it verifies                                                         |
| ------------------------------------------------ | ------------------------------------------------------------------------ |
| `test_known_face_emits_observation`              | `_update_last_face` emits FaceObservation with person_id, name, is_known |
| `test_no_obs_engine_no_crash`                    | `_update_last_face` with obs_engine=None still works                     |
| `test_unknown_face_emits_observation`            | Unknown face emits FaceObservation with person_id=None, is_known=False   |
| `test_get_context_prefers_working_memory`        | `_get_context()` returns fused context from working_memory               |
| `test_get_context_falls_back_when_expired`       | Falls back to last_face/last_scene when working_memory expired (None)    |
| `test_get_context_no_working_memory`             | Falls back to dicts when working_memory is None                          |
| `test_build_context_text_prefers_working_memory` | `_build_context_text()` uses working_memory context                      |
| `test_build_context_text_falls_back_no_wm`       | Falls back to last_face when no working_memory                           |
| `test_device_snapshot_from_working_memory`       | `device_snapshot()` reads DeviceObservation from working_memory          |
| `test_device_snapshot_no_device_obs`             | Returns {} when context has no DeviceObservation                         |
| `test_device_snapshot_expired_context`           | Returns {} when working_memory context is expired                        |

---

## What this enables

1. **"Siapa ini?" proactive trigger** — `CurrentContext.speech` is now populated
   via `SpeechObservation` → `ProactivePlanner._check_unknown_person()` fires when
   unknown face + user talking.

2. **Device telemetry tools** — `battery_status`, `network_status`,
   `device_information` return real data from device data channel when
   `DeviceObservation` is in the fused context.

3. **30s TTL** — Stale context expires. `working_memory.get()` returns `None`
   after 30s of no observations, forcing the agent to fall back to fresh
   `last_face`/`last_scene` dicts or re-perceive.

4. **1s fusion window** — Deduped observations from multiple sources within a
   1-second window. Multiple face detections in the same window fold into one
   `CurrentContext` with deduped `visible_people`.

---

## Live verification plan

1. **Speech tracking**: Talk to agent → check worker log for
   `observation queued: SpeechObservation` and `context updated: speech=...`

2. **Device telemetry**: Send device data via dashboard data channel
   (`{"battery_level": 72, "wifi_connected": true}`) → ask agent "berapa baterai?"
   → agent calls `battery_status` → returns `{"battery_level": 72, "available": true}`

3. **"Siapa ini?" trigger**: Point camera at unknown face → start talking →
   within 30s planner should fire "Siapa ini?" prompt (check worker log for
   `planner trigger: unknown_person`)

4. **Fusion**: Point camera at known face → check `context updated: people=['Asep']`
   in log within 1s

5. **TTL**: Stop camera for 35s → check `working_memory.get()` returns None →
   agent falls back to dicts or returns no context

---

## Architecture after Step 5

```
Video frame
  → FaceRecognizer → _update_last_face()
    → tool_ctx.last_face = {dict}           (tools read this, unchanged)
    → obs_engine.emit(FaceObservation)      (NEW: feeds fusion)

  → SceneUnderstander (every 5 frames)
    → tool_ctx.last_scene = {dict}          (tools read this, unchanged)
    → obs_engine.emit(SceneObservation)     (NEW: feeds fusion)

Audio (AgentSession)
  → user_input_transcribed event
    → if is_final: obs_engine.emit(SpeechObservation)  (NEW)

Data channel "device" topic
  → handle_data_received()
    → obs_engine.emit(DeviceObservation)    (NEW: was just logged before)

ObservationEngine (1s fusion window)
  → fuse(batch) → CurrentContext
  → WorkingMemory.set(CurrentContext)       (30s TTL)

Agent._get_context()
  → working_memory.get() → CurrentContext    (NEW: has speech + device + TTL)
  → fallback: last_face + last_scene dicts   (existing)

device_snapshot()
  → working_memory.get() → find DeviceObservation  (NEW)
  → fallback: {}                             (existing)
```
