"""Speaker — Gemini Live 24kHz PCM → LiveKit AudioSource.

Gemini Live outputs audio as inline_data Blob (mime_type audio/pcm;rate=24000, raw
16-bit little-endian PCM mono). We wrap each chunk in an rtc.AudioFrame and feed the
AudioSource; the source backs a LocalAudioTrack published to the room.

Ponytail: one thin adapter. No resampling — the AudioSource sample_rate matches the
Gemini output rate (settings.gemini_audio_output_sample_rate=24000), so frames pass
through unchanged. Ponytail: no partial-chunk stitching; PCM chunks are frame-aligned
by Gemini, each is a valid independent AudioFrame.
"""

from __future__ import annotations

import logging

from env import get_settings
from livekit import rtc

log = logging.getLogger(__name__)

# Gemini Live PCM: 16-bit signed little-endian, mono, 24000 Hz.
_SAMPLE_RATE = get_settings().gemini_audio_output_sample_rate
_CHANNELS = get_settings().gemini_audio_output_channels
_BYTES_PER_SAMPLE = 2  # 16-bit


class Speaker:
    """Bridges Gemini audio blobs → a LiveKit published audio track.

    One Speaker per room. publish(room) creates the AudioSource + track and publishes
    it; feed(blob) pushes PCM chunks; close() unpublishs. Frame size is derived from
    the chunk length — Gemini sends frame-aligned PCM, so any chunk length that is a
    whole multiple of (bytes_per_sample * channels) is a valid frame.
    """

    def __init__(self, *, source: rtc.AudioSource | None = None) -> None:
        self._source = source or rtc.AudioSource(sample_rate=_SAMPLE_RATE, num_channels=_CHANNELS)
        self._track: rtc.LocalAudioTrack | None = None
        self._pub: rtc.LocalTrackPublication | None = None

    def publish(self, room: rtc.Room) -> None:
        """Create + publish the audio track to the room's local participant."""
        self._track = rtc.LocalAudioTrack.create_audio_track("memora-voice", self._source)
        self._pub = room.local_participant.publish_track(self._track, rtc.TrackPublishOptions())
        log.info("speaker track published")

    def feed(self, pcm: bytes) -> None:
        """Push a raw 16-bit PCM chunk into the AudioSource.

        `pcm` is the Blob.data bytes from a Gemini audio part (mime_type
        audio/pcm;rate=24000). We compute samples_per_channel from the byte length.
        """
        if not pcm:
            return
        frame_bytes = _BYTES_PER_SAMPLE * _CHANNELS
        if len(pcm) % frame_bytes != 0:
            # ponytail: trim to a whole-frame boundary rather than stash the tail
            pcm = pcm[: (len(pcm) // frame_bytes) * frame_bytes]
            if not pcm:
                return
        samples_per_channel = len(pcm) // frame_bytes
        frame = rtc.AudioFrame(pcm, _SAMPLE_RATE, _CHANNELS, samples_per_channel)
        self._source.capture_frame(frame)

    async def aclose(self) -> None:
        if self._pub is not None:
            try:
                self._track and await self._track._unpublish()  # noqa: SLF001
            except Exception:  # noqa: BLE001
                log.debug("speaker unpublish failed", exc_info=True)


# --- self-check: frame math is whole for aligned PCM ---
def _self_check() -> None:  # pragma: no cover
    # 24000 Hz * 1 ch * 2 bytes = 48000 bytes/sec. A 100ms chunk = 4800 bytes.
    chunk = b"\x00" * 4800
    frame_bytes = _BYTES_PER_SAMPLE * _CHANNELS
    assert len(chunk) % frame_bytes == 0
    spc = len(chunk) // frame_bytes
    assert spc == 2400  # 100ms at 24kHz
    # odd length trims cleanly
    odd = b"\x00" * 4801
    trimmed = odd[: (len(odd) // frame_bytes) * frame_bytes]
    assert len(trimmed) == 4800
    print(f"speaker self-check OK: {spc} samples/chunk, trim={len(trimmed)}")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
