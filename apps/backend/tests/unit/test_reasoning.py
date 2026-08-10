"""Unit tests — reasoning: GeminiLiveSession message routing + reconnect, ReasoningAgent
wiring, Speaker frame math, Display publish, system-prompt placeholder.

No live connection: sessions are stubbed; the agent's collaborators are MagicMocks.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import live, types

from dto.observations import CurrentContext, SpeechObservation
from reasoning.agent.agent import ReasoningAgent
from reasoning.prompts.system import build_system_instruction
from reasoning.response.display import _MAX_PAYLOAD, Display
from reasoning.response.speaker import Speaker
from reasoning.session.live_session import GeminiLiveSession
from tools import ToolContext


def _session_with_ctx(ctx: ToolContext | None = None) -> GeminiLiveSession:
    s = GeminiLiveSession(client=MagicMock())
    s._ctx = ctx or ToolContext()
    return s


class TestSystemPrompt:
    def test_placeholder_replaced(self) -> None:
        filled = build_system_instruction("Orang: Asep. Lokasi: apotek.")
        assert "{{context_package}}" not in filled
        assert "Asep" in filled and "apotek" in filled

    def test_empty_gets_default(self) -> None:
        base = build_system_instruction("")
        assert "{{context_package}}" not in base
        assert "(belum ada konteks)" in base


class TestLiveSessionRouting:
    def _stub(self):
        class _Stub:
            def __init__(self):
                self.sent = []

            async def send_tool_response(self, *, function_responses):
                self.sent.extend(function_responses)

        return _Stub()

    async def test_handle_text_and_tool_call(self) -> None:
        s = _session_with_ctx()
        received: list[str] = []
        # _handle awaits on_text → must be an awaitable callable
        s._on_text = AsyncMock(side_effect=received.append)
        s._session = self._stub()
        s.set_turn_complete_callback(AsyncMock())

        import tools.registry as reg

        async def _fw(args, ctx):
            return {"firmware_version": "test"}

        orig = reg.build_registry()
        reg._REGISTRY = {**orig, "firmware_version": _fw}
        try:
            msg = types.LiveServerMessage(
                server_content=types.LiveServerContent(
                    model_turn=types.Content(parts=[types.Part(text="Halo Asep!")], role="model"),
                    turn_complete=True,
                ),
                tool_call=types.LiveServerToolCall(
                    function_calls=[types.FunctionCall(id="c1", name="firmware_version", args={})]
                ),
            )
            await s._handle(msg)
        finally:
            reg._REGISTRY = orig

        assert received == ["Halo Asep!"]
        assert len(s._session.sent) == 1
        assert s._session.sent[0]["name"] == "firmware_version"

    async def test_transcription_final_and_interim(self) -> None:
        s = _session_with_ctx()
        seen: list[tuple[str, bool]] = []
        s._on_transcription = AsyncMock(side_effect=lambda t, final: seen.append((t, final)))
        sc = types.LiveServerContent(
            input_transcription=types.Transcription(text="apa ini?"),
            interim_input_transcription=types.Transcription(text="apa in"),
        )
        await s._handle_content(sc)
        assert seen == [("apa ini?", True), ("apa in", False)]

    async def test_turn_complete_fires_callback(self) -> None:
        s = _session_with_ctx()
        cb = AsyncMock()
        s.set_turn_complete_callback(cb)
        await s._handle_content(types.LiveServerContent(turn_complete=True))
        cb.assert_awaited_once()
        # generation_complete also fires
        cb.reset_mock()
        await s._handle_content(types.LiveServerContent(generation_complete=True))
        cb.assert_awaited_once()

    async def test_audio_part_to_sink(self) -> None:
        s = _session_with_ctx()
        fed: list[bytes] = []
        s.set_audio_sink(fed.append)
        blob = types.Blob(mime_type="audio/pcm;rate=24000", data=b"\x00\x01")
        await s._handle_audio(blob)
        assert fed == [b"\x00\x01"]
        # empty blob no-op
        await s._handle_audio(types.Blob(data=b""))
        assert len(fed) == 1

    async def test_start_receive_requires_connect(self) -> None:
        s = GeminiLiveSession(client=MagicMock())
        with pytest.raises(RuntimeError, match="connect"):
            s.start_receive()

    async def test_send_video_audio_noop_without_session(self) -> None:
        s = _session_with_ctx()
        assert s._session is None
        await s.send_video(b"jpeg")
        await s.send_audio(b"\x00", sample_rate=16000)  # must not raise

    async def test_send_video_audio_forward(self) -> None:
        fake_session = MagicMock()
        fake_session.send_realtime_input = AsyncMock()
        s = _session_with_ctx()
        s._session = fake_session
        await s.send_video(b"jpeg")
        fake_session.send_realtime_input.assert_awaited_once()
        assert fake_session.send_realtime_input.await_args.kwargs["video"].mime_type == "image/jpeg"
        await s.send_audio(b"\x00\x01", sample_rate=8000)
        call = fake_session.send_realtime_input.await_args.kwargs["audio"]
        assert call.mime_type == "audio/pcm;rate=8000"

    async def test_reconnect_loop_restores_session(self) -> None:
        class _FakeLive:
            class _Stable:
                # receive() must be a sync method returning an async generator —
                # _receive_loop does `async for msg in self._session.receive()`.
                def receive(self):
                    return _block_forever()

            async def connect(self, *, model, config):
                self.calls = getattr(self, "calls", 0) + 1
                return self._Stable()

        async def _block_forever():
            await asyncio.Event().wait()
            yield types.LiveServerMessage()

        class _FakeClient:
            class aio:
                live = _FakeLive()

        class _Dropping:
            def __init__(self):
                self.dropped = False

            def receive(self):
                async def _gen():
                    if not self.dropped:
                        self.dropped = True
                        raise live.ConnectionClosed(None, "drop")
                    yield types.LiveServerMessage()

                return _gen()

        s2 = GeminiLiveSession(client=_FakeClient())
        s2._ctx = ToolContext()
        s2._backoff_s = 0.0
        s2._max_backoff_s = 0.0
        s2._session = _Dropping()

        loop_task = asyncio.create_task(s2._receive_loop())
        for _ in range(500):
            if s2._session is not None and not isinstance(s2._session, _Dropping):
                break
            await asyncio.sleep(0.01)
        s2._closing = True
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass
        assert s2._session is not None and not isinstance(s2._session, _Dropping)
        assert s2._backoff_s == 1.0


class TestReasoningAgent:
    def _agent(self) -> ReasoningAgent:
        session = MagicMock()
        session.connect = AsyncMock()
        session.aclose = AsyncMock()
        session.send_video = AsyncMock()
        session.send_audio = AsyncMock()
        session.start_receive = MagicMock()
        session.set_audio_sink = MagicMock()
        session.set_turn_complete_callback = MagicMock()
        engine = MagicMock()
        engine.build = AsyncMock(return_value=(MagicMock(), "ctx text"))
        speaker = MagicMock()
        speaker.publish = MagicMock()
        speaker.aclose = AsyncMock()
        display = MagicMock()
        display.show = AsyncMock()
        agent = ReasoningAgent(
            room=MagicMock(),
            tool_ctx=ToolContext(),
            engine=engine,
            session=session,
            speaker=speaker,
            display=display,
        )
        return agent

    async def test_start_wires_everything(self) -> None:
        agent = self._agent()
        await agent.start(current=None)
        agent.engine.build.assert_awaited_once()
        agent.session.set_audio_sink.assert_called_once_with(agent.speaker.feed)
        agent.session.set_turn_complete_callback.assert_called_once()
        agent.session.connect.assert_awaited_once()
        agent.speaker.publish.assert_called_once_with(agent.room)
        agent.session.start_receive.assert_called_once()
        assert agent._connected

    async def test_on_turn_calls_extract(self) -> None:
        agent = self._agent()
        calls: list[str] = []
        agent.on_extract = lambda t: calls.append(t)
        agent.ctx.current_context = CurrentContext(speech="apa ini?")
        await agent._on_turn()
        assert calls == ["apa ini?"]

    async def test_on_turn_no_speech_no_extract(self) -> None:
        agent = self._agent()
        called = False

        async def _extract(t):
            nonlocal called
            called = True

        agent.on_extract = _extract
        await agent._on_turn()
        assert not called

    async def test_on_turn_extract_failure_caught(self) -> None:
        agent = self._agent()

        async def _boom(t):
            raise RuntimeError("db down")

        agent.on_extract = _boom
        agent.ctx.current_context = CurrentContext(speech="x")
        await agent._on_turn()  # must not raise

    async def test_on_transcription_final_emits(self) -> None:
        emitted: list[object] = []

        async def _emit(obs):
            emitted.append(obs)

        agent = self._agent()
        agent.emit_observation = _emit
        await agent._on_transcription("apa ini?", is_final=True)
        await agent._on_transcription("apa in", is_final=False)  # interim skipped
        await agent._on_transcription("   ", is_final=True)  # empty skipped
        assert len(emitted) == 1
        assert isinstance(emitted[0], SpeechObservation)
        assert emitted[0].transcript == "apa ini?"

    async def test_feed_delegates(self) -> None:
        agent = self._agent()
        await agent.feed_video(b"jpeg")
        agent.session.send_video.assert_awaited_once_with(b"jpeg")
        await agent.feed_audio(b"\x00", sample_rate=16000)
        agent.session.send_audio.assert_awaited_once_with(b"\x00", sample_rate=16000)

    async def test_update_context_refreshes(self) -> None:
        agent = self._agent()
        ctx = CurrentContext(scene="apotek")
        await agent.update_context(ctx)
        assert agent.ctx.current_context is ctx

    async def test_stop_closes_session_and_speaker(self) -> None:
        agent = self._agent()
        await agent.start(current=None)
        await agent.stop()
        agent.session.aclose.assert_awaited_once()
        agent.speaker.aclose.assert_awaited_once()
        assert not agent._connected


class TestSpeaker:
    def _speaker(self):
        source = MagicMock()
        return Speaker(source=source), source

    def test_feed_full_chunk(self) -> None:
        spk, source = self._speaker()
        spk.feed(b"\x00" * 4800)  # 100ms @ 24kHz mono
        source.capture_frame.assert_called_once()
        frame = source.capture_frame.call_args.args[0]
        assert frame.samples_per_channel == 2400

    def test_feed_odd_length_trimmed(self) -> None:
        spk, source = self._speaker()
        spk.feed(b"\x00" * 4801)  # +1 byte → trimmed to 4800
        frame = source.capture_frame.call_args.args[0]
        assert frame.samples_per_channel == 2400

    def test_feed_empty_noop(self) -> None:
        spk, source = self._speaker()
        spk.feed(b"")
        source.capture_frame.assert_not_called()

    def test_feed_too_short_trims_to_zero(self) -> None:
        spk, source = self._speaker()
        spk.feed(b"\x00")  # 1 byte < 2-byte frame → dropped
        source.capture_frame.assert_not_called()


class TestDisplay:
    async def test_publish(self) -> None:
        pub = AsyncMock()  # pub IS the publish_data callable Display.show awaits
        await Display(SimpleRoom(pub)).show("halo")
        pub.assert_awaited_once_with("halo", reliable=True, topic="display")

    async def test_empty_noop(self) -> None:
        pub = AsyncMock()
        await Display(SimpleRoom(pub)).show("")
        pub.assert_not_called()

    async def test_long_truncated(self) -> None:
        pub = AsyncMock()
        await Display(SimpleRoom(pub)).show("x" * 5000)
        sent = pub.await_args.args[0]
        assert len(sent) == _MAX_PAYLOAD


class SimpleRoom:
    def __init__(self, pub) -> None:
        self.local_participant = SimpleNamespace(publish_data=pub)
