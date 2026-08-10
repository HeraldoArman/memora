# Memora — Backend & DB Foundation Progress

**Date:** 2026-08-10 14:02
**Branch:** develop
**Scope:** backend + DB foundation (firmware skipped). Plan: `tidy-painting-shamir.md` (Phases 0–7).

---

## Summary

All 8 phases complete. Runnable backend that joins a LiveKit room as an agent, perceives
camera+audio, recognizes faces, forms/consolidates long-term memories across
Postgres/Neo4j/FAISS, and reasons with Gemini Live (event-driven, tool-calling).
Deploy target: Railway CPU (`faiss-cpu` + CPU torch pinned).

Real services wired via adapters — **LiveKit Cloud** + **Google Gemini API**. Keys live in
`apps/backend/.env` (placeholder values committed; user fills real keys later). Missing
keys fail loudly at startup via pydantic-settings validation.

---

## What was built

### Shared packages

- `packages/config/env/` — pydantic-settings `Settings`, `get_settings()` singleton, required-env fail-loud validation.
- `packages/shared/` — DTOs (`observations`, `knowledge`, `tools`, `memory`), JSON schemas for Gemini (`TOOLS_BLOCK`, extraction schema), constants (thresholds, TTLs, enums), prompts (Bahasa persona), utils.
- `packages/database/` — Postgres (SQLAlchemy async + asyncpg + Alembic, first migration), Neo4j (`AsyncGraphDatabase` driver + queries + repos), FAISS (`IndexFlatIP(512)` + sidecar person_id map + `FaceRepository`).

### Backend (apps/backend)

- **api/** — FastAPI `create_app()` + `/health` + lifespan (DB engines, Neo4j, FAISS load).
- **perception/** — InsightFace `FaceRecognizer` (lazy-loaded, CPU), frame sampler (1 FPS), speech forwarder (16kHz PCM → Gemini), observation engine (1s fusion window) + working memory (30s TTL).
- **extraction/ + pipeline/** — non-live `generate_content` structured extraction, rule-first normalizer, resolver, classifier, verifier, consolidator. Event-triggered `PipelineRunner`.
- **context/** — retriever → ranker → summarizer → packager → `ContextEngine.build()`.
- **tools/** — 24 registered tools across person/memory/reminder/calendar/observation/system + `registry` + `ToolContext`.
- **reasoning/** — `GeminiLiveSession` (Live connect, tool router, transcription feed, turn boundaries), `ReasoningAgent` (wires perception → Gemini → speaker/display → extraction), `Speaker` (24kHz PCM → LiveKit AudioSource), `Display` (text → OLED data channel).
- **gateway/** — LiveKit `JobContext` entrypoint, track handler (video+audio loops), data channel (device telemetry).
- **workers/** — `livekit_worker.py` (`agents.cli.run_app`).

### No user/device accounts

Single implicit device per room (hackathon IoT), no multi-user auth — per explicit requirement.

---

## Verification

### Self-checks (all pass, ruff clean)

```
reasoning.session.live_session    2 OK (routing + reconnect)
reasoning.agent.agent             1 OK
reasoning.tools.router            1 OK
reasoning.response.speaker        1 OK
reasoning.response.display        1 OK
reasoning.prompts.system          1 OK
gateway.livekit.track_handler     1 OK
gateway.livekit.entrypoint        1 OK
gateway.livekit.data_channel      1 OK
perception.observation.engine     1 OK
perception.observation.working_memory  1 OK
perception.speech.forwarder       1 OK
perception.vision.sampler         1 OK
```

`uv run ruff check apps/backend/ packages/` → **All checks passed!**

### End-to-end wiring integration test

`scripts/verify/phase6_wiring.py` proves the full data path at every seam (transport mocked:
rtc + genai live; REAL perception/observation/memory/context/tools/speaker/display):

```
[1] session start: engine + agent connected, sink + turn cb wired
[2] video loop: face recognized → emitted → frame forwarded to Gemini
[3] audio loop: SpeechForwarder → shim → feed_audio → Gemini
[4] tool_call: current_scene → router → tool → response (scene=apotek)
[5] model text → display → publish_data(topic=display)
[6] model audio → speaker → AudioSource.capture_frame (100ms @ 24kHz)
[7] data_channel: device telemetry → DeviceObservation emitted
[8] turn_complete → on_extract → pipeline runner (speech='Siapa ini?')
[9] session.stop: tasks cancelled, agent + live session closed
```

### Not verifiable locally (needs real keys)

- Live room loop: `GEMINI_API_KEY=dummy` + `LIVEKIT_URL=wss://your-project.livekit.cloud`
  (placeholders) block a live connect. Once real keys are in `.env`:
  `uv run python -m workers.livekit_worker` then join a room with a webcam+mic client.
- InsightFace model load (~300MB buffalo_l, needs network; lazy first-detect).

---

## Phase 7 hardening applied

1. **Reconnection** — `GeminiLiveSession._receive_loop` re-opens the live session on
   drop/error with capped exponential backoff (1s → 5s ceiling), reset on success.
   Perception + memory loops are independent tasks and keep running throughout; feeds
   (`send_video`/`send_audio`) are no-ops while disconnected, resume on reconnect.
2. **Graceful degradation** — perception loops catch+log per-frame errors and keep the
   loop alive; tool failures return `{"error": ...}` to the model (it can explain or
   re-call); extraction hook failures don't kill the room.
3. **Event-driven gating** — proactivity conservative (`proactive_audio=False`); turn
   boundaries from `turn_complete`/`generation_complete`, transcription is a continuous
   observation feed, not a turn gate.
4. **Bug fixed** — `LiveConnectConfig` was being passed `model=...`, which is
   `extra_forbidden` on the installed google-genai — would have crashed every real
   connect. Removed; `model` now goes only to `client.aio.live.connect(model=...)`.
   Guarded by a config-build assertion in the self-check.

---

## Files added (this session)

- `apps/backend/reasoning/` — `session/live_session.py`, `agent/agent.py`, `tools/router.py`,
  `response/{speaker,display}.py`, `prompts/system.py`, `__init__.py` re-exports.
- `apps/backend/tools/` — `registry.py` + `person|memory|reminder|calendar|observation|system/`.
- `apps/backend/gateway/` — `session.py`, `livekit/{entrypoint,track_handler,data_channel}.py`.
- `apps/backend/workers/livekit_worker.py`.
- `apps/backend/scripts/verify/phase6_wiring.py` — e2e wiring integration test.
- `packages/shared/dto/observations.py` — added `embedding` field to `FaceObservation`.

---

## Next steps (when real keys available)

1. Fill `apps/backend/.env`: `GEMINI_API_KEY`, `LIVEKIT_URL/API_KEY/API_SECRET`.
2. `bun run db:start` + `bun run db:migrate` (if not already seeded).
3. `uv run python -m workers.livekit_worker` (agent worker).
4. Join a LiveKit room with webcam+mic client → verify face→context→Gemini→audio→OLED loop.
5. Full demo PRD journeys (meet person → register → recall; pharmacy reminder; "why did I come here?").

No git commit made (per instruction).
