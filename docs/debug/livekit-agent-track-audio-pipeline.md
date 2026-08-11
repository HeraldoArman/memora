# LiveKit agent worker: no track subscription, no audio, no display output

- **Date:** 2026-08-11
- **Service:** `backend-worker` (LiveKit agent worker) + `dashboard` (dummy device harness)
- **Status:** RESOLVED (2026-08-11). Three root causes across the pipeline.
- **Branch:** `develop`

## TL;DR

The dashboard connected to LiveKit and published camera + mic tracks, but the
agent worker never subscribed to them, so no audio/video reached Gemini Live.
Text prompts (sent via the `"prompt"` data channel topic) worked — proving the
Gemini → display path was fine, but the audio input path was completely broken.
Three separate bugs:

1. **Track subscription not firing.** `ctx.connect(auto_subscribe=True)` did not
   reliably fire `track_subscribed` for tracks published before the agent joined
   (race condition). Fixed by adding a `track_published` handler with explicit
   `pub.set_subscribed(True)` and a post-connect loop that subscribes to tracks
   from participants already in the room.

2. **Audio forwarder crash.** `rtc.AudioStream` yields `AudioFrameEvent` (which
   wraps `AudioFrame` at `.frame`), not `AudioFrame` directly. The forwarder
   accessed `frame.data` → `AttributeError: 'AudioFrameEvent' object has no
attribute 'data'` → audio loop crashed immediately on every frame.

3. **Speaker audio silent.** `rtc.AudioSource.capture_frame()` is an async
   coroutine, but `Speaker.feed()` called it synchronously without awaiting →
   `RuntimeWarning: coroutine 'AudioSource.capture_frame' was never awaited`
   → no audio ever reached the published speaker track.

**Bonus fix:** `GEMINI_TEXT_MODEL=gemini-2.5-flash` was deprecated (404 NOT_FOUND),
causing the scene understander to fail every frame. Changed to
`gemini-2.5-flash-lite`.

---

## System context

```
apps/backend/
  gateway/livekit/entrypoint.py      → per-room job handler (track + data wiring)
  gateway/livekit/track_handler.py   → handle_video_track / handle_audio_track
  perception/speech/forwarder.py      → SpeechForwarder: AudioStream → Gemini Live
  reasoning/session/live_session.py  → Gemini Live connection (receive loop)
  reasoning/response/speaker.py       → Speaker: Gemini PCM → LiveKit AudioSource
  reasoning/response/display.py       → Display: model text → data channel topic="display"
  reasoning/agent/agent.py            → ReasoningAgent (owns Gemini + Speaker + Display)
  workers/livekit_worker.py           → AgentServer + rtc_session registration
apps/dashboard/
  src/components/device-harness.tsx   → dummy device: camera + mic + prompt input
  src/app/api/token/route.ts          → token mint with RoomAgentDispatch
```

Data flow:

```
Dashboard (browser camera/mic)
  → LiveKit tracks published (video + audio)
  → Agent worker subscribes (track_subscribed event)
  → handle_video_track → FrameSampler → face identity + Gemini video
  → handle_audio_track → SpeechForwarder → Gemini Live audio input
  → Gemini Live response → output_transcription → Display.show → data channel "display"
  → Gemini Live response → audio blob → Speaker.feed → AudioSource → LiveKit audio track
  → Dashboard receives data channel "display" → OLED display renders text
```

---

## Bug 1: Track subscription not firing

### Symptom

Worker logs showed `job connected to room` and `room session started` but **no**
`track_subscribed` events. The dashboard's camera/mic tracks were published
(verified in browser console: `localTrackPublished` for both audio + video),
but the agent never subscribed to them.

### Root cause

`ctx.connect(auto_subscribe=True)` should auto-subscribe, but there's a race:
if the participant publishes tracks **before** the agent connects (common — the
dashboard connects first, then the agent is dispatched), the auto-subscribe
logic in `JobContext.connect` only processes participants discovered after
connect. Tracks from already-present participants are visible in
`room.remote_participants` but not auto-subscribed.

### Fix

`apps/backend/gateway/livekit/entrypoint.py` — three changes:

1. Added `track_published` handler that explicitly calls `pub.set_subscribed(True)`
   for any new track publication from a remote participant.

2. Added a post-`ctx.connect()` loop that iterates `room.remote_participants`,
   logs existing participants + their tracks, and calls `pub.set_subscribed(True)`
   on any unsubscribed track. If the track is already subscribed and has a
   `.track` attribute, it immediately spawns the video/audio handler.

3. Added `track_subscription_failed` handler for diagnostics.

```python
@room.on("track_published")
def _on_track_pub(pub: rtc.RemoteTrackPublication, p: rtc.RemoteParticipant):
    log.info("track published: sid=%s kind=%s from %s — subscribing", pub.sid, pub.kind, p.identity)
    pub.set_subscribed(True)

# After ctx.connect():
for p in room.remote_participants.values():
    for pub in p.track_publications.values():
        if not pub.subscribed:
            pub.set_subscribed(True)
        if pub.subscribed and pub.track:
            # spawn handle_video_track / handle_audio_track
```

---

## Bug 2: Audio forwarder crash (`AudioFrameEvent` vs `AudioFrame`)

### Symptom

```
AttributeError: 'AudioFrameEvent' object has no attribute 'data'
```

The audio loop crashed on the very first frame. No audio ever reached Gemini Live.

### Root cause

`rtc.AudioStream.__aiter__` yields `AudioFrameEvent` objects, not `AudioFrame`
objects directly. `AudioFrameEvent` is a dataclass with a single field:

```python
@dataclass
class AudioFrameEvent:
    frame: AudioFrame  # the actual AudioFrame is at .frame, not at .data
```

The forwarder accessed `frame.data` (the `AudioFrame.data` attribute) but
`frame` was actually an `AudioFrameEvent` — which has `.frame`, not `.data`.

### Fix

`apps/backend/perception/speech/forwarder.py` — unwrap the event:

```python
async for frame in self.audio_stream:
    audio_frame = frame.frame if hasattr(frame, "frame") else frame
    blob = types.Blob(mime_type=AUDIO_MIME, data=bytes(audio_frame.data))
    await self.live_session.send_realtime_input(audio=blob)
```

The `hasattr` guard keeps it compatible with both `AudioFrameEvent` (new API)
and bare `AudioFrame` (older API / manual feeding).

---

## Bug 3: Speaker audio silent (`capture_frame` not awaited)

### Symptom

```
RuntimeWarning: coroutine 'AudioSource.capture_frame' was never awaited
```

Gemini audio responses were received (output_transcription fragments logged)
but no audio played on the dashboard's speaker.

### Root cause

`rtc.AudioSource.capture_frame()` is an `async` method (it awaits an FFI
queue internally). `Speaker.feed()` was a sync method calling
`self._source.capture_frame(frame)` — returning a coroutine that was never
awaited. The audio frame was never pushed to the AudioSource.

### Fix

`apps/backend/reasoning/response/speaker.py` — schedule the coroutine on the
event loop without blocking the receive loop:

```python
def feed(self, pcm: bytes) -> None:
    ...
    asyncio.ensure_future(self._source.capture_frame(frame))
```

`asyncio.ensure_future` is correct here because `feed()` is called from the
Gemini receive loop (which runs inside an event loop). The coroutine is
scheduled and the receive loop continues immediately — no blocking.

---

## Bonus: Scene understander model deprecated (404)

### Symptom

```
scene understanding failed: 404 NOT_FOUND. {'error': {'message': 'This model
models/gemini-2.5-flash is no longer available to new users...'}}
```

Every frame triggered a failed Gemini call at ~1 FPS.

### Fix

`apps/backend/.env` — `GEMINI_TEXT_MODEL=gemini-2.5-flash` → `gemini-2.5-flash-lite`.
This model is used by the scene understander, context summarizer, and extractor.

---

## Diagnostic tooling: text prompt via data channel

To test the Gemini → display pipeline without relying on audio tracks, a text
prompt input was added to the dashboard:

- Dashboard: text input + Send button publishes to topic `"prompt"` via
  `room.localParticipant.publishData()`.
- Worker: `data_received` handler checks `topic == "prompt"`, decodes the text,
  and calls `agent.feed_prompt(text)` → `session.send_text(text)` → Gemini
  processes it as user input → responds with audio + output_transcription.

This isolates the Gemini path from the audio track path. If text prompts work
but voice doesn't, the issue is in the audio track subscription/forwarder.
If text prompts also don't work, the issue is in the Gemini connection or
display path.

### Files changed

- `apps/dashboard/src/components/device-harness.tsx` — prompt input UI + publish
- `apps/backend/gateway/livekit/entrypoint.py` — `"prompt"` topic handler
- `apps/backend/reasoning/agent/agent.py` — `feed_prompt()` method

---

## Key LiveKit APIs learned

- **`Room.on("track_published")`** — fires when a remote participant publishes
  a track. Call `publication.set_subscribed(True)` to subscribe explicitly.
  This is the reliable way to subscribe when `auto_subscribe` misses tracks
  published before the agent joined.

- **`Room.on("track_subscribed")`** — fires after subscription completes.
  Arguments: `(track: rtc.Track, publication: rtc.RemoteTrackPublication,
participant: rtc.RemoteParticipant)`.

- **`Room.on("data_received")`** — fires for data channel messages.
  Argument: `packet: rtc.DataPacket` with `.data` (bytes), `.topic` (str),
  `.participant` (RemoteParticipant).

- **`rtc.AudioStream`** — `async for frame in stream` yields `AudioFrameEvent`
  (not `AudioFrame`). Access the frame via `frame.frame`, data via
  `frame.frame.data`.

- **`rtc.AudioSource.capture_frame()`** — async method. Must be awaited or
  scheduled via `asyncio.ensure_future()`. Calling it synchronously silently
  drops the frame.

- **`JobContext.connect(auto_subscribe=True)`** — does NOT reliably subscribe
  to tracks from participants already in the room. Always add a fallback loop
  over `room.remote_participants` after connect.

- **`JobContext.wait_for_participant()`** — returns a participant that matches
  the given identity, or the first participant to join if `identity=None`.
  Useful for blocking the entrypoint until the device connects.

- **Named agents require explicit dispatch.** `RoomAgentDispatch` must be set
  in the token's `roomConfig` for the agent to be dispatched to the room.
  Import from `livekit-server-sdk` (not `@livekit/protocol`).

---

## Verification

After all three fixes, the full pipeline works:

1. Dashboard connects → publishes camera + mic
2. Worker logs: `track published` → `track SUBSCRIBED` for both audio + video
3. Worker logs: `audio track subscribed from dummy-device`
4. Text prompt "can you hear my voices and video?" → Gemini responds
5. Worker logs: `output_transcription fragment` → `flush → on_text`
6. Worker logs: `display.show → publish topic=display`
7. Dashboard console: `[DataReceived] topic= display len= 53 text= Ya, saya bisa mendengar suara Anda dan melihat video.`
8. OLED display renders the response text
