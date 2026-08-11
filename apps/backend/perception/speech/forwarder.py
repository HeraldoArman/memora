"""Speech forwarder — LiveKit AudioStream → Gemini Live.

Reads AudioFrames from a LiveKit AudioStream (16kHz mono in), forwards as realtime audio
to the Gemini Live session via send_realtime_input(audio=Blob). Gemini expects raw PCM
little-endian int16. AudioFrame.data is already PCM int16 bytes; we just wrap in a Blob
with the right mime type. No resampling here for the forward path — Gemini Live handles
the input sample rate; if needed, add a resample step (lazy: out of scope for MVP).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# PCM 16-bit little-endian, 16kHz, mono — matches AudioFrame default from a mic source.
# Gemini Live accepts audio/pcm;rate=16000.
AUDIO_MIME = "audio/pcm;rate=16000"


class SpeechForwarder:
    """Forward LiveKit audio frames into a Gemini Live session."""

    def __init__(self, audio_stream, live_session) -> None:
        self.audio_stream = audio_stream
        self.live_session = live_session

    async def run(self) -> None:
        """Consume the AudioStream forever, forwarding each frame to Gemini Live."""
        from google.genai import types

        async for frame in self.audio_stream:
            audio_frame = frame.frame if hasattr(frame, "frame") else frame
            blob = types.Blob(mime_type=AUDIO_MIME, data=bytes(audio_frame.data))
            await self.live_session.send_realtime_input(audio=blob)

    async def forward(self, frame) -> None:
        """Forward a single AudioFrame to Gemini Live (manual feeding)."""
        from google.genai import types

        audio_frame = frame.frame if hasattr(frame, "frame") else frame
        blob = types.Blob(mime_type=AUDIO_MIME, data=bytes(audio_frame.data))
        await self.live_session.send_realtime_input(audio=blob)


# --- self-check: Blob construction ---
def _self_check() -> None:  # pragma: no cover
    from google.genai import types

    blob = types.Blob(mime_type=AUDIO_MIME, data=b"\x00\x01\x02\x03")
    assert blob.mime_type == AUDIO_MIME
    assert blob.data == b"\x00\x01\x02\x03"
    print(f"forwarder self-check OK: mime={blob.mime_type} bytes={len(blob.data)}")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
