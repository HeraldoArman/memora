# Future Plans — Deferred Enhancements

**Branch:** `refactor/agent-session-gemini`
**Date:** 2026-08-12

Features deliberately deferred from Steps 4-5. Each has real value but adds
failure modes that aren't justified until the foundation is stable.

---

## 1. Speech in CurrentContext (for Proactive Planner "Siapa ini?" trigger)

**Status:** Deferred from Step 4
**Depends on:** Step 5 (ObservationEngine) or a lightweight speech-tracking shim

### What it does

The `ProactivePlanner` has a `_check_unknown_person()` trigger that fires
when an unknown face is visible AND the user is talking (`current.speech` is
non-empty). This injects a "Siapa ini?" prompt to the agent, prompting it to
ask the user who they're talking to so the person can be registered.

### Why it was deferred

Without ObservationEngine, `CurrentContext.speech` is always `None`. The
trigger never fires. The system prompt already instructs the agent to ask
"Siapa ini?" for unknown faces via the `visible_people` tool — the planner
trigger is a safety net, not the primary mechanism.

Wiring speech tracking without the full observation stack introduces:

- **No TTL**: Speech from 10 minutes ago would still satisfy the trigger. Need
  a timestamp + expiry check.
- **Interim vs final transcripts**: `user_input_transcribed` fires on interim
  transcripts too. Need to filter for `is_final=True` or the trigger fires on
  partial words.
- **Speaker ambiguity**: Without ObservationEngine, speech is a bare string
  with no speaker context. The planner can't distinguish user speech from
  agent speech. If the agent is generating a reply, buffered audio from a
  previous turn might falsely satisfy "user is talking."
- **Collision with system prompt**: Both the planner trigger and the model's
  own "Siapa ini?" can fire near-simultaneously — the user gets asked twice.

### Implementation plan (when ready)

**Option A — Lightweight shim (no ObservationEngine):**

1. In `entrypoint.py`, listen to `user_input_transcribed` on `AgentSession`:
   ```python
   @session.on("user_input_transcribed")
   def _on_transcript(ev):
       if ev.is_final:
           tool_ctx.last_speech = ev.transcript
           tool_ctx._speech_deadline = time.monotonic() + 30.0
   ```
2. In `agent.py` `_get_context()`, read `tool_ctx.last_speech` if within TTL:
   ```python
   speech = None
   if tool_ctx.last_speech and time.monotonic() < tool_ctx._speech_deadline:
       speech = tool_ctx.last_speech
   return CurrentContext(visible_people=visible, scene=scene, speech=speech)
   ```
3. Add `last_speech: str | None = None` and `_speech_deadline: float = 0.0` to
   `ToolContext`.

~15 lines. Still has the speaker ambiguity and collision problems.

**Option B — Full ObservationEngine (Step 5):**

1. Wire `ObservationEngine` + `WorkingMemory` (see Step 5 in roadmap).
2. Listen to `user_input_transcribed` → emit `SpeechObservation` to
   `obs_engine.emit()`.
3. The observation engine fuses speech into `CurrentContext.speech` with a
   30s TTL — solves the staleness problem automatically.
4. The fusion window naturally filters interim transcripts (only final
   observations are emitted).
5. Speaker disambiguation requires correlating with agent output transcription
   (`conversation_item_added` with `role="assistant"`) — the observation
   engine can suppress speech observations while the agent is talking.

~80 lines total (includes the full Step 5 wiring). Robust but heavy.

**Recommendation:** Option B (Step 5). The lightweight shim trades correctness
for simplicity — the speaker ambiguity alone makes it unreliable. Wait for
Step 5.

---

## 2. ObservationEngine + WorkingMemory (Step 5)

**Status:** Optional, deferred
**Depends on:** Nothing (independent)

See `roadmap.md` Step 5 for the full plan. Summary of what it adds:

- 1s fusion window (dedup observations from multiple sources)
- 30s TTL on context (stale context expires)
- Single write path (no race conditions)
- Device telemetry processing (battery, button, wifi)
- Enables speech tracking (Option B above)

Re-enable when:

- Multi-sensor fusion is needed (GPS + IMU + face + scene)
- Device telemetry needs to trigger actions (low battery alert)
- The direct dict approach proves insufficient
- Speech in CurrentContext is needed for the "Siapa ini?" trigger
