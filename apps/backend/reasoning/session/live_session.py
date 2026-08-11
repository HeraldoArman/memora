"""GeminiLiveSession — one live Gemini connection driving reasoning + audio out + tools.

Owns the AsyncSession from client.aio.live.connect(). Three concurrent loops run for
the connection lifetime:
  - _receive_loop: iterate session.receive(); route server messages:
      * server_content → model text (→ display) + audio parts (→ speaker) +
        input/output transcription (→ observation feed) + turn_complete/generation_complete
        (→ turn boundary signal).
      * tool_call → dispatch via ToolRouter → session.send_tool_response.
  - send_realtime_input is driven externally (perception pushes video frames + audio
    chunks through send_video / send_audio), NOT by an internal loop.
  - the connection is closed on aclose().

Arch decisions honored:
  - tools + systemInstruction fixed at connect (immutable); dynamic context via tool
    results. The context package is injected into the system prompt ONCE at connect.
  - transcription = continuous observation feed, not a turn boundary (plan decision #3).
    We emit transcription via the on_transcription callback but never gate turns on it.
  - turn boundaries = turn_complete / generation_complete on server_content.

Ponytail: no retry/backoff on transient API errors here — that's Phase 7 hardening.
The receive loop logs and exits on ConnectionClosed; the gateway/agent owns reconnect.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from env import get_settings
from google import genai
from google.genai import live, types

from reasoning.prompts.system import build_system_instruction
from reasoning.tools.router import dispatch_tool_call
from schemas import TOOLS_BLOCK
from tools import ToolContext

log = logging.getLogger(__name__)


class GeminiLiveSession:
    """A single Gemini Live connection bound to one room/agent.

    Lifecycle: connect(room, ctx, *, on_text, on_transcription) → start_receive() →
    (perception calls send_video/send_audio) → aclose(). The speaker + display are
    wired here so audio out + OLED publish happen inline in the receive loop.
    """

    def __init__(self, client: genai.Client | None = None) -> None:
        self._client = client or genai.Client(api_key=get_settings().gemini_api_key)
        self._session: live.AsyncSession | None = None
        self._receive_task: asyncio.Task | None = None
        # wiring set at connect()
        self._ctx: ToolContext | None = None
        self._on_text: Callable[[str], Awaitable[None]] | None = None
        self._on_transcription: Callable[[str, bool], Awaitable[None]] | None = None
        # reconnect bookkeeping (Phase 7 hardening)
        self._closing = False  # set by aclose() to stop the reconnect loop
        self._context_text = ""  # re-seed the system prompt on each reconnect
        # ponytail: capped exponential backoff; 5s ceiling is enough for a hackathon
        self._backoff_s = 1.0
        self._max_backoff_s = 5.0

    async def connect(
        self,
        *,
        ctx: ToolContext,
        context_text: str = "",
        on_text: Callable[[str], Awaitable[None]] | None = None,
        on_transcription: Callable[[str, bool], Awaitable[None]] | None = None,
    ) -> None:
        """Open the live connection with the immutable tool surface + system instruction.

        `context_text` is the initial context package (rendered Bahasa text). `on_text`
        fires for model text parts (for the display); `on_transcription(text, is_final)`
        fires for input speech transcription (for the observation feed). The context text
        is retained so the receive loop can re-seed the system prompt on reconnect.
        """
        self._ctx = ctx
        self._on_text = on_text
        self._on_transcription = on_transcription
        self._context_text = context_text
        await self._open()

    async def _open(self) -> None:
        """(Re)open the Gemini Live connection with the stored tool surface + system prompt.

        Called once at connect() and again on each reconnect from the receive loop. The
        config is rebuilt from the immutable inputs (tools, system_instruction, modalities)
        — arch decision #2: dynamic context flows via tool calls, not the system prompt,
        so reseeding the original context_text on reconnect is correct.
        """
        cfg = types.LiveConnectConfig(
            system_instruction=build_system_instruction(self._context_text),
            tools=[TOOLS_BLOCK],
            response_modalities=[types.Modality.AUDIO, types.Modality.TEXT],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            # Conservative proactivity: don't auto-narrate scene changes (plan risk #2).
            proactivity=types.ProactivityConfig(proactive_audio=False),
        )
        self._session = await self._client.aio.live.connect(
            model=get_settings().gemini_live_model, config=cfg
        )
        log.info("gemini live connected (model=%s)", get_settings().gemini_live_model)

    def start_receive(self) -> asyncio.Task:
        """Spawn the receive loop as a background task."""
        if self._session is None:
            raise RuntimeError("connect() first")
        self._closing = False
        self._receive_task = asyncio.create_task(self._receive_loop(), name="gemini-receive")
        return self._receive_task

    async def _receive_loop(self) -> None:
        """Receive server messages forever; reconnect with backoff on drop.

        Phase 7 hardening: if the connection closes or errors (transient network, API
        hiccup), the loop re-opens the live session and keeps going. Perception + memory
        loops are independent tasks and keep running throughout — they push into
        send_video/send_audio which are no-ops while `self._session is None`. aclose()
        sets `_closing` to break the loop.
        """
        while not self._closing:
            if self._session is None:
                await self._reconnect()
                continue
            try:
                async for msg in self._session.receive():
                    if self._closing:
                        return
                    await self._handle(msg)
                # receive() ended cleanly (server closed stream) → reconnect
                self._session = None
            except asyncio.CancelledError:
                raise
            except live.ConnectionClosed:
                log.info("gemini live connection closed; reconnecting")
                self._session = None
            except Exception:  # noqa: BLE001 — don't die; reconnect loop owns retries
                log.exception("gemini receive loop error; reconnecting")
                self._session = None

    async def _reconnect(self) -> None:
        """Re-open the live session with capped exponential backoff."""
        await asyncio.sleep(self._backoff_s)
        try:
            await self._open()
            self._backoff_s = 1.0  # reset on success
            log.info("gemini live reconnected")
        except Exception:  # noqa: BLE001 — transient connect failures are the norm here
            self._backoff_s = min(self._backoff_s * 2, self._max_backoff_s)
            log.warning("gemini reconnect failed; backoff=%.1fs", self._backoff_s)

    async def _handle(self, msg: types.LiveServerMessage) -> None:
        sc = msg.server_content
        if sc is not None:
            await self._handle_content(sc)
        if msg.tool_call is not None:
            await self._handle_tool_call(msg.tool_call)

    async def _handle_content(self, sc: types.LiveServerContent) -> None:
        # transcription = continuous feed (decision #3); emit even mid-turn.
        # input_transcription = final transcript (is_final=True); interim = partial.
        if self._on_transcription is not None:
            if sc.input_transcription:
                await self._on_transcription(sc.input_transcription.text, True)
            if sc.interim_input_transcription:
                await self._on_transcription(sc.interim_input_transcription.text, False)
        # model turn parts: text → display, audio → speaker.
        turn = sc.model_turn
        if turn is not None:
            for part in turn.parts or []:
                if part.text and self._on_text is not None:
                    await self._on_text(part.text)
                # audio is handled by the agent/speaker wiring via an audio sink set
                # at connect; the blob flows through _handle_audio.
                if part.inline_data:
                    await self._handle_audio(part.inline_data)
        # turn boundary signals (decision #3): turn_complete/generation_complete.
        if sc.turn_complete or sc.generation_complete:
            await self._on_turn_complete()

    async def _handle_audio(self, blob: types.Blob) -> None:
        """Forward a model audio blob to the speaker sink if attached."""
        sink = getattr(self, "_audio_sink", None)
        if sink is None or not blob.data:
            return
        # Gemini PCM mime: audio/pcm;rate=24000
        sink(blob.data)

    def set_audio_sink(self, sink: Callable[[bytes], None]) -> None:
        """Attach the speaker.feed callable as the audio out sink."""
        self._audio_sink = sink

    async def _handle_tool_call(self, tool_call: types.LiveServerToolCall) -> None:
        assert self._session is not None and self._ctx is not None
        responses = await dispatch_tool_call(tool_call, self._ctx)
        if responses:
            await self._session.send_tool_response(function_responses=responses)

    async def _on_turn_complete(self) -> None:
        """Hook for turn boundaries — used by the agent to trigger extraction."""
        cb = getattr(self, "_on_turn_complete_cb", None)
        if cb is not None:
            await cb()

    def set_turn_complete_callback(self, cb: Callable[[], Awaitable[None]]) -> None:
        self._on_turn_complete_cb = cb

    # --- perception input (called externally by the sampler/forwarder) ---
    async def send_video(self, jpeg: bytes) -> None:
        """Push a video frame (JPEG bytes) to the live session, ≤1 FPS."""
        if self._session is None:
            return
        await self._session.send_realtime_input(video=types.Blob(mime_type="image/jpeg", data=jpeg))

    async def send_audio(self, pcm: bytes, *, sample_rate: int = 16000) -> None:
        """Push an audio chunk (16-bit PCM) to the live session."""
        if self._session is None:
            return
        await self._session.send_realtime_input(
            audio=types.Blob(mime_type=f"audio/pcm;rate={sample_rate}", data=pcm)
        )

    async def send_text(self, text: str) -> None:
        """Push a text instruction to the live session (proactive planner trigger)."""
        if self._session is None or not text:
            return
        await self._session.send_realtime_input(text=text)

    async def aclose(self) -> None:
        self._closing = True
        if self._receive_task is not None:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._receive_task = None
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:  # noqa: BLE001
                log.debug("session close failed", exc_info=True)
        self._session = None
        log.info("gemini live session closed")


# --- self-check: config + message routing logic (no live connection) ---
def _self_check() -> None:  # pragma: no cover
    import asyncio

    # build_system_instruction + LiveConnectConfig construction don't require a live
    # connection; verify the config shape + message routing with a fake session.
    s = GeminiLiveSession(client=genai.Client(api_key="dummy"))
    assert s._session is None
    # the LiveConnectConfig must build without a live connection — guards against
    # regressions like passing `model` into the config (extra_forbidden).
    s._ctx = ToolContext()
    s._context_text = ""
    cfg = types.LiveConnectConfig(
        system_instruction=build_system_instruction(""),
        tools=[TOOLS_BLOCK],
        response_modalities=[types.Modality.AUDIO, types.Modality.TEXT],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        proactivity=types.ProactivityConfig(proactive_audio=False),
    )
    assert cfg.tools, "config must carry the tool surface"
    assert "Memora" in str(cfg.system_instruction), "system instruction missing persona"

    # route a fake server message with text + tool_call through _handle using a stub session
    received_text: list[str] = []
    received_transcripts: list[tuple[str, bool]] = []

    async def fake_on_text(t: str) -> None:
        received_text.append(t)

    async def fake_on_transcription(t: str, is_final: bool) -> None:
        received_transcripts.append((t, is_final))

    # stub session capturing send_tool_response
    class _StubSession:
        def __init__(self):
            self.sent = []

        async def send_tool_response(self, *, function_responses):
            self.sent.extend(function_responses)

    s._session = _StubSession()  # type: ignore[assignment]
    s._ctx = ToolContext()
    s._on_text = fake_on_text
    s._on_transcription = fake_on_transcription

    # patch registry so firmware_version resolves
    import tools.registry as reg

    async def _fw(args, ctx):
        return {"firmware_version": "test"}

    orig = reg.build_registry()
    reg._REGISTRY = {**orig, "firmware_version": _fw}
    try:
        part = types.Part(text="Halo Asep!")
        turn = types.Content(parts=[part], role="model")
        sc = types.LiveServerContent(model_turn=turn, turn_complete=True)
        fc = types.FunctionCall(id="c1", name="firmware_version", args={})
        tc = types.LiveServerToolCall(function_calls=[fc])
        msg = types.LiveServerMessage(server_content=sc, tool_call=tc)
        asyncio.run(s._handle(msg))
    finally:
        reg._REGISTRY = orig

    assert received_text == ["Halo Asep!"]
    assert len(s._session.sent) == 1  # type: ignore[attr-defined]
    assert s._session.sent[0]["name"] == "firmware_version"  # type: ignore[attr-defined]
    print("live_session self-check OK: text→on_text, tool_call→send_tool_response")

    # --- transcription is_final routing: input=final, interim=partial ---
    sc = types.LiveServerContent(
        input_transcription=types.Transcription(text="apa ini?"),
        interim_input_transcription=types.Transcription(text="apa in"),
    )
    asyncio.run(s._handle_content(sc))
    assert received_transcripts == [("apa ini?", True), ("apa in", False)], received_transcripts
    print("live_session self-check OK: input_transcription→final, interim→partial")

    # --- Phase 7: reconnect loop ---
    async def _check_reconnect() -> None:
        import time

        # fake client whose live.connect returns a stable session, so a retry restores it
        class _FakeAsyncLive:
            def __init__(self):
                self.calls = 0

            class _StableSession:
                def receive(self):
                    async def _gen():
                        # block forever: a live session that's connected but idle
                        await asyncio.Event().wait()
                        yield types.LiveServerMessage()

                    return _gen()

            async def connect(self, *, model, config):
                self.calls += 1
                return self._StableSession()

        class _FakeClient:
            class aio:
                live = _FakeAsyncLive()

        # stub session whose receive() raises ConnectionClosed once, then is replaced
        # (the loop sets self._session = None and re-opens via the fake client)

        class _DroppingSession:
            def __init__(self):
                self.dropped = False

            def receive(self):
                async def _gen():
                    if not self.dropped:
                        self.dropped = True
                        raise live.ConnectionClosed(None, "drop")
                    yield types.LiveServerMessage()

                return _gen()

        s2 = GeminiLiveSession(client=_FakeClient())  # type: ignore[arg-type]
        s2._ctx = ToolContext()
        s2._backoff_s = 0.0  # no real sleep
        s2._max_backoff_s = 0.0
        s2._session = _DroppingSession()  # type: ignore[assignment]

        loop_task = asyncio.create_task(s2._receive_loop())
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if s2._session is not None and not isinstance(s2._session, _DroppingSession):
                break
            await asyncio.sleep(0.01)
        s2._closing = True
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass
        assert s2._session is not None, "reconnect did not restore session"
        assert not isinstance(s2._session, _DroppingSession), "still on dropped session"
        assert s2._backoff_s == 1.0, "backoff not reset on success"

    asyncio.run(_check_reconnect())
    print("live_session self-check OK: reconnect loop restores session after drop")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
