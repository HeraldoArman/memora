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
from typing import Any

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
        # live.connect() is an async context manager; we enter it manually so the
        # websocket stays open across the receive loop and reconnects (not a one-shot
        # `async with` block). _cm is the entered cm; exited on close/reconnect.
        self._cm: Any = None
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
        # ponytail: pending prompts queued during reconnect; flushed on successful _open()
        self._pending_prompts: list[str] = []
        # ponytail: recent conversation turns for context re-injection on reconnect.
        # Gemini Live 1011 errors drop the WS and lose conversation context; re-injecting
        # the last few turns as a text prompt after reconnect lets the model pick up.
        self._recent_turns: list[str] = []
        self._MAX_TURNS = 6
        # output transcription arrives in fragments (finished=None) across a turn; we
        # accumulate them and flush the full sentence to on_text (OLED) at turn boundary,
        # so the display shows one coherent line instead of flickering per-fragment.
        self._out_buf = ""

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
        # ponytail: retry with backoff — Gemini Live WS can time out on first connect
        while True:
            try:
                await self._open()
                return
            except Exception:
                log.warning("gemini live connect failed; retrying in %.1fs", self._backoff_s)
                await asyncio.sleep(self._backoff_s)
                self._backoff_s = min(self._backoff_s * 2, self._max_backoff_s)

    async def _open(self) -> None:
        """(Re)open the Gemini Live connection with the stored tool surface + system prompt.

        Called once at connect() and again on each reconnect from the receive loop. The
        config is rebuilt from the immutable inputs (tools, system_instruction, modalities)
        — arch decision #2: dynamic context flows via tool calls, not the system prompt,
        so reseeding the original context_text on reconnect is correct.
        """
        # ponytail: native-audio Live models are AUDIO-only (TEXT modality is rejected
        # — "combination of response modalities (AUDIO, TEXT) is not supported"). To
        # still drive the glasses OLED, we enable output_audio_transcription: the model's
        # spoken response is transcribed server-side and arrives as
        # LiveServerContent.output_transcription, which we route to on_text (Display).
        cfg = types.LiveConnectConfig(
            system_instruction=build_system_instruction(self._context_text),
            tools=[TOOLS_BLOCK],
            response_modalities=[types.Modality.AUDIO],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            # ponytail: proactivity config omitted — gemini-2.0-flash-exp rejected the
            # `proactivity` field. Re-add ProactivityConfig when GEMINI_LIVE_MODEL moves
            # to a 2.5+ Live model that supports it.
        )
        # connect() returns an async context manager (yields AsyncSession). Enter it
        # manually so the session persists beyond a single `async with` block — the
        # receive loop + reconnects drive its lifetime via _close_cm().
        self._cm = self._client.aio.live.connect(model=get_settings().gemini_live_model, config=cfg)
        self._session = await self._cm.__aenter__()
        log.info("gemini live connected (model=%s)", get_settings().gemini_live_model)
        # flush any prompts queued during the reconnect window
        if self._pending_prompts:
            for p in self._pending_prompts:
                await self._session.send_realtime_input(text=p)
            log.info("flushed %d pending prompt(s)", len(self._pending_prompts))
            self._pending_prompts.clear()
        # ponytail: re-inject recent conversation turns so the model doesn't lose context
        # after a 1011 reconnect. Sent as a single text block before any new input.
        if self._recent_turns:
            summary = "Riwayat percakapan sebelumnya:\n" + "\n".join(self._recent_turns)
            await self._session.send_realtime_input(text=summary)
            log.info("re-injected %d recent turn(s) after reconnect", len(self._recent_turns))

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
                await self._close_cm()
                self._session = None
            except asyncio.CancelledError:
                raise
            except live.ConnectionClosed:
                log.info("gemini live connection closed; reconnecting")
                await self._close_cm()
                self._session = None
            except Exception:  # noqa: BLE001 — don't die; reconnect loop owns retries
                log.exception("gemini receive loop error; reconnecting")
                await self._close_cm()
                self._session = None

    async def _close_cm(self) -> None:
        """Exit the live.connect() context manager if entered (closes the websocket).
        Safe to call when already closed / never opened."""
        cm, self._cm = self._cm, None
        if cm is None:
            return
        try:
            await cm.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001 — best-effort teardown on a possibly-dead ws
            log.debug("live cm exit failed", exc_info=True)

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
                log.info("input_transcription(final): %r", sc.input_transcription.text[:120])
                await self._on_transcription(sc.input_transcription.text, True)
            if sc.interim_input_transcription:
                await self._on_transcription(sc.interim_input_transcription.text, False)
        # output_transcription = the model's spoken response transcribed server-side.
        # Native-audio Live models are AUDIO-only (no TEXT modality), so this is the
        # text source for the glasses OLED (on_text → Display). The API streams it in
        # fragments (finished=None) across a turn; we accumulate and flush the full
        # sentence once at the turn boundary so the OLED shows one coherent line
        # instead of flickering per-fragment.
        if sc.output_transcription and self._on_text is not None:
            t = sc.output_transcription
            if t.text:
                self._out_buf += t.text
                log.info(
                    "output_transcription fragment: %r (buf=%d)", t.text[:120], len(self._out_buf)
                )
        # model turn parts: text parts are internal reasoning traces (the **Identifying...**
        # narration) — log them but DON'T send to display. Only output_transcription (the
        # spoken response) goes to on_text. Audio parts → speaker.
        turn = sc.model_turn
        if turn is not None:
            for part in turn.parts or []:
                if part.text:
                    log.info("model reasoning (not displayed): %r", part.text[:120])
                # audio is handled by the agent/speaker wiring via an audio sink set
                # at connect; the blob flows through _handle_audio.
                if part.inline_data:
                    await self._handle_audio(part.inline_data)
        # turn boundary signals (decision #3): turn_complete/generation_complete.
        if sc.turn_complete or sc.generation_complete:
            log.info(
                "turn boundary (turn_complete=%s gen_complete=%s) — flushing out_buf len=%d",
                sc.turn_complete,
                sc.generation_complete,
                len(self._out_buf),
            )
            # flush the accumulated output transcription to the OLED, then reset.
            if self._out_buf and self._on_text is not None:
                log.info("flush → on_text len=%d text=%r", len(self._out_buf), self._out_buf[:120])
                await self._on_text(self._out_buf)
                self._recent_turns.append(f"Asisten: {self._out_buf}")
                self._recent_turns = self._recent_turns[-self._MAX_TURNS :]
            self._out_buf = ""
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
        try:
            await self._session.send_realtime_input(
                video=types.Blob(mime_type="image/jpeg", data=jpeg)
            )
        except Exception:  # noqa: BLE001 — ws closed; receive loop reconnects
            log.debug("send_video dropped (connection closed)")

    async def send_audio(self, pcm: bytes, *, sample_rate: int = 16000) -> None:
        """Push an audio chunk (16-bit PCM) to the live session."""
        if self._session is None:
            return
        try:
            await self._session.send_realtime_input(
                audio=types.Blob(mime_type=f"audio/pcm;rate={sample_rate}", data=pcm)
            )
        except Exception:  # noqa: BLE001 — ws closed; receive loop reconnects
            log.debug("send_audio dropped (connection closed)")

    async def send_text(self, text: str) -> None:
        """Push a text instruction to the live session (proactive planner trigger)."""
        if not text:
            return
        self._recent_turns.append(f"Pengguna: {text}")
        self._recent_turns = self._recent_turns[-self._MAX_TURNS :]
        if self._session is None:
            self._pending_prompts.append(text)
            log.info("prompt queued (reconnecting): %r", text[:80])
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
        # exit the live.connect() cm (closes the websocket); _session is invalid after.
        await self._close_cm()
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
        response_modalities=[types.Modality.AUDIO],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
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

    assert received_text == []  # model_turn text is reasoning, not displayed
    assert len(s._session.sent) == 1  # type: ignore[attr-defined]
    assert s._session.sent[0]["name"] == "firmware_version"  # type: ignore[attr-defined]
    print("live_session self-check OK: text reasoning not displayed, tool_call→send_tool_response")

    # --- transcription is_final routing: input=final, interim=partial ---
    sc = types.LiveServerContent(
        input_transcription=types.Transcription(text="apa ini?"),
        interim_input_transcription=types.Transcription(text="apa in"),
    )
    asyncio.run(s._handle_content(sc))
    assert received_transcripts == [("apa ini?", True), ("apa in", False)], received_transcripts
    print("live_session self-check OK: input_transcription→final, interim→partial")

    # --- output_transcription → accumulate → flush at turn boundary (OLED text) ---
    # Native-audio models stream output_transcription in fragments (finished=None);
    # we accumulate and emit the full sentence once on turn_complete/generation_complete.
    received_text.clear()
    s._out_buf = ""
    sc = types.LiveServerContent(
        output_transcription=types.Transcription(text="Saya ", finished=None)
    )
    asyncio.run(s._handle_content(sc))  # fragment 1 → buffered, not emitted
    assert received_text == [], received_text
    sc = types.LiveServerContent(
        output_transcription=types.Transcription(text="asisten memora.", finished=None)
    )
    asyncio.run(s._handle_content(sc))  # fragment 2 → buffered, not emitted
    assert received_text == [], received_text
    sc = types.LiveServerContent(turn_complete=True)
    asyncio.run(s._handle_content(sc))  # turn boundary → flush
    assert received_text == ["Saya asisten memora."], received_text
    assert s._out_buf == "", "buffer not reset after flush"
    print("live_session self-check OK: output_transcription fragments accumulated → flush at turn")

    # --- Phase 7: reconnect loop ---
    async def _check_reconnect() -> None:
        import contextlib
        import time

        # fake client whose live.connect returns an async cm yielding a stable session,
        # so a retry restores it (matches the real google-genai connect() contract).

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

            @contextlib.asynccontextmanager
            async def connect(self, *, model, config):
                self.calls += 1
                yield self._StableSession()

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
