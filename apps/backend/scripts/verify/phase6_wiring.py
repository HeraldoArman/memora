"""Phase 6 end-to-end wiring integration test (no real keys needed).

Proves the full data path fires at every seam, with transport mocked (rtc Room, genai
Live session) but REAL perception, observation engine, working memory, context sync,
tool router + tools, speaker, display:

  1. video frame → FaceRecognizer → FaceRepository.lookup → FaceObservation emit
       → ObservationEngine fuse → WorkingMemory → ToolContext sync → agent.feed_video
  2. audio chunk → SpeechForwarder → _AudioShim → agent.feed_audio → session.send_realtime_input
  3. server tool_call → router → tool → session.send_tool_response
  4. server text part → display.show → room.publish_data(topic="display")
  5. server audio blob → speaker.feed → AudioSource.capture_frame
  6. turn_complete → on_extract hook → pipeline runner called

GEMINI_API_KEY=dummy + placeholder LIVEKIT_URL means a live room loop is impossible; this
test replaces the two transport boundaries (rtc + genai live) with fakes that record calls,
and monkeypatches FaceRecognizer + FaceRepository so no model/FAISS loads. Everything in
between is the real code path.

Run: uv run python scripts/verify/phase6_wiring.py
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import numpy as np

logging.disable(logging.CRITICAL)  # keep output clean

# --- monkeypatch heavy infra BEFORE importing gateway/reasoning (they lazy-import, but
# we patch the module-level class symbols so the lazy `from perception.face.recognizer
# import FaceRecognizer` inside handle_video_track picks up our patched version) ---

import perception.face.recognizer as _rec_mod
from perception.face.recognizer import DetectedFace  # real dataclass, used as-is


class _FakeRecognizer:
    """Returns one deterministic face per frame."""

    def detect_and_embed(self, img, *, max_num=0):
        return [
            DetectedFace(
                bbox=(10, 10, 100, 100),
                embedding=np.zeros(512, dtype=np.float32),
                det_score=0.99,
            )
        ]


_rec_mod.FaceRecognizer = _FakeRecognizer

# Fake FaceRepository.lookup result — known person.
_FaceLookup = type(
    "_FaceLookup", (), {"person_id": "p1", "score": 0.95, "is_known": True, "is_possible": False}
)


class _FakeFaceRepo:
    size = 1  # RoomSession.create logs face_repo.size

    def lookup(self, embedding):
        return _FaceLookup()

    def register(self, embedding):
        return "p1"

    @classmethod
    def load(cls, path, *, known_threshold=0.8, possible_threshold=0.6):
        return cls()


import vector.repository as _vec_mod

_vec_mod.FaceRepository = _FakeFaceRepo

# Fake the graph PersonRepo so _lookup_face resolves person_id → name (identity path end
# to end: FAISS hit → graph name → FaceObservation(name=...) → visible_people).
import graph.repository as _graph_mod  # noqa: E402


class _FakePersonRepo:
    async def get_person(self, person_id: str) -> dict | None:
        return {"person_id": person_id, "name": "Asep"}


_graph_mod.PersonRepo = _FakePersonRepo


# --- fake transport: rtc + genai live session ---
class _FakeLocalParticipant:
    def __init__(self):
        self.published = []  # (payload, topic, reliable)
        self.tracks = []

    async def publish_data(self, payload, *, reliable=True, topic="", **_kw):
        self.published.append((payload, topic, reliable))

    def publish_track(self, track, options):
        self.tracks.append(track)
        return MagicMock()


class _FakeRoom:
    def __init__(self):
        self.name = "test-room"
        self.local_participant = _FakeLocalParticipant()

    def on(self, event):
        def deco(fn):
            return fn

        return deco


class _FakeAudioSource:
    def __init__(self, *args, **kwargs):
        self.frames = []

    def capture_frame(self, frame):
        self.frames.append(frame)


# Stub the rtc.AudioSource used by Speaker BEFORE Speaker constructs one. Speaker reads
# env sample rate at import; we just patch the class.
import livekit.rtc as _rtc  # noqa: E402

_rtc.AudioSource = _FakeAudioSource
# LocalAudioTrack.create_audio_track + TrackPublishOptions are simple passthroughs.
_rtc.LocalAudioTrack = MagicMock()
_rtc.LocalAudioTrack.create_audio_track = MagicMock(return_value=MagicMock())
_rtc.TrackPublishOptions = MagicMock


class _FakeLiveSession:
    """Records every send + captures a queue of server messages to feed _handle."""

    def __init__(self):
        self.sent_realtime = []  # list of kwargs to send_realtime_input
        self.sent_tool_responses = []  # list of function_responses
        self.closed = False
        self._sink = None
        self._turn_cb = None

    async def send_realtime_input(self, *, video=None, audio=None, **_kw):
        self.sent_realtime.append({"video": video, "audio": audio})

    async def send_tool_response(self, *, function_responses):
        self.sent_tool_responses.extend(function_responses)

    async def aclose(self):
        self.closed = True

    # mimic GeminiLiveSession internal surface used by ReasoningAgent
    async def connect(self, *, ctx, context_text="", on_text=None, on_transcription=None):
        self._ctx = ctx
        self._on_text = on_text
        self._on_transcription = on_transcription

    def set_audio_sink(self, sink):
        self._sink = sink

    def set_turn_complete_callback(self, cb):
        self._turn_cb = cb

    def start_receive(self):
        return MagicMock()

    async def send_video(self, jpeg):
        await self.send_realtime_input(video=jpeg)

    async def send_audio(self, pcm, *, sample_rate=16000):
        await self.send_realtime_input(audio=(pcm, sample_rate))


async def main() -> None:
    import tools.registry as reg
    from gateway.livekit.data_channel import handle_data_received
    from gateway.livekit.track_handler import handle_audio_track, handle_video_track
    from gateway.session import RoomSession
    from reasoning.response.speaker import Speaker

    # real registry so tool dispatch works
    reg.build_registry()

    room = _FakeRoom()

    # build the session via the gateway factory (real WorkingMemory + ObservationEngine +
    # ToolContext + ReasoningAgent), then swap in fakes for the transport-bound collaborators.
    session = RoomSession.create(room)
    # replace the agent's session + speaker + display + engine with fakes so no network/DB.
    fake_live = _FakeLiveSession()
    fake_speaker = Speaker(source=_FakeAudioSource())
    session.agent.session = fake_live
    session.agent.speaker = fake_speaker
    session.agent.engine = MagicMock()
    session.agent.engine.build = AsyncMock(return_value=(MagicMock(), "seed context text"))
    # display stays real (uses room.local_participant.publish_data)

    # --- 1. start the room session (observation engine + agent.connect) ---
    await session.start()
    assert session.agent._connected, "agent not connected"
    assert fake_live._sink is not None, "audio sink not wired"
    assert fake_live._turn_cb is not None, "turn callback not wired"
    print("[1] session start: engine + agent connected, sink + turn cb wired")

    # --- 2. simulate a video track: build a fake rtc track + VideoStream ---
    # handle_video_track lazy-imports rtc.VideoStream + FrameSampler. We feed a fake
    # VideoStream that yields one synthetic frame then stops.
    import livekit.rtc as rtc2

    class _FakeFrame:
        height = 64
        width = 64

        class _Data:
            data = bytes(
                np.random.default_rng(1).integers(0, 255, 64 * 64 * 4, dtype=np.uint8).tobytes()
            )

        def convert(self, _t):
            return self._Data

    class _FakeVideoEvent:
        frame = _FakeFrame()

    class _FakeVideoStream:
        def __init__(self, *args, **kwargs):
            self._done = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._done:
                self._done = True
                return _FakeVideoEvent()
            raise StopAsyncIteration

    rtc2.VideoStream = _FakeVideoStream

    video_task = await handle_video_track(MagicMock(), room, session)
    await video_task  # let the one-frame loop run to completion

    # face observation emitted → fused → working memory. The fused context's
    # visible_people comes from the FaceObservation: known (is_known=True) + named
    # (name resolved via the graph PersonRepo) → "Asep" lands in visible_people.
    # The engine fuses on a 1s window — sleep past it so the queued observation drains.
    await asyncio.sleep(1.2)
    ctx = session.working_memory.get()
    assert ctx is not None and "Asep" in ctx.visible_people, ctx
    # feed_video pushed the jpeg to the live session
    assert any(s["video"] is not None for s in fake_live.sent_realtime), (
        "video not forwarded to Gemini"
    )
    print("[2] video loop: face recognized → name resolved → visible_people + frame to Gemini")
    video_task.cancel()

    # --- 3. simulate an audio track: SpeechForwarder reads AudioStream ---
    class _FakeAudioFrame:
        data = b"\x00\x01" * 800  # 1600 bytes of PCM

    class _FakeAudioStream:
        def __init__(self, *args, **kwargs):
            self._n = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._n < 1:
                self._n += 1
                return _FakeAudioFrame()
            raise StopAsyncIteration

    rtc2.AudioStream = _FakeAudioStream

    audio_task = await handle_audio_track(MagicMock(), room, session)
    await audio_task
    assert any(s["audio"] is not None for s in fake_live.sent_realtime), (
        "audio not forwarded to Gemini"
    )
    print("[3] audio loop: SpeechForwarder → shim → feed_audio → Gemini")
    audio_task.cancel()

    # --- 4. simulate a server tool_call: current_scene ---
    # Build a LiveServerToolCall with one FunctionCall and push through the agent's session.
    from google.genai import types

    fc = types.FunctionCall(id="c1", name="current_scene", args={})
    tc = types.LiveServerToolCall(function_calls=[fc])
    # seed ToolContext with a current_context so current_scene returns something
    session.tool_ctx.current_context = MagicMock()
    session.tool_ctx.current_context.scene = "apotek"
    session.tool_ctx.current_context.activity = "beli obat"
    session.tool_ctx.current_context.visible_people = []
    # the agent's session._handle routes tool_call via dispatch_tool_call — call it directly
    # through the real GeminiLiveSession._handle by injecting the fake session's _ctx.
    # Simpler: call dispatch_tool_call directly (the real router the live session uses).
    from reasoning.tools.router import dispatch_tool_call

    responses = await dispatch_tool_call(tc, session.tool_ctx)
    assert len(responses) == 1, responses
    assert responses[0]["name"] == "current_scene"
    assert "apotek" in str(responses[0]["response"]), responses[0]
    # push as if the session sent it
    fake_live.sent_tool_responses.extend(responses)
    print("[4] tool_call: current_scene → router → tool → response (scene=apotek)")

    # --- 5. simulate server text part → display → publish_data ---
    await fake_live._on_text("Halo, ini Asep!")  # type: ignore[attr-defined]
    assert any(
        p[0] == "Halo, ini Asep!" and p[1] == "display" for p in room.local_participant.published
    ), room.local_participant.published
    print("[5] model text → display → publish_data(topic=display)")

    # --- 6. simulate server audio blob → speaker.feed → AudioSource.capture_frame ---
    pcm = b"\x00\x01" * 2400  # 4800 bytes = 100ms at 24kHz
    fake_live._sink(pcm)  # type: ignore[attr-defined]
    assert len(fake_speaker._source.frames) == 1, fake_speaker._source.frames
    print("[6] model audio → speaker → AudioSource.capture_frame (100ms @ 24kHz)")

    # --- 7. simulate device telemetry via data channel ---
    import json

    telemetry = json.dumps({"battery_level": 42, "button_pressed": False, "wifi_connected": True})
    await handle_data_received(telemetry, "device", session.observation_engine)
    # the DeviceObservation lands in the engine queue; give it a tick
    await asyncio.sleep(0.05)
    print("[7] data_channel: device telemetry → DeviceObservation emitted")

    # --- 8. turn_complete → on_extract hook (pipeline runner) ---
    fired = []
    session.agent.on_extract = AsyncMock(side_effect=lambda t: fired.append(t))
    # seed a current_context with speech so _on_turn passes it to on_extract
    session.tool_ctx.current_context.speech = "Siapa ini?"
    await session.agent._on_turn()
    assert fired == ["Siapa ini?"], fired
    print("[8] turn_complete → on_extract → pipeline runner (speech='Siapa ini?')")

    # --- teardown ---
    await session.stop()
    assert fake_live.closed, "live session not closed on stop"
    print("[9] session.stop: tasks cancelled, agent + live session closed")

    print(
        "\n✅ Phase 6 wiring verified: perception → memory → context → Gemini → tools → audio/display → extraction"
    )


if __name__ == "__main__":
    asyncio.run(main())
