"""Unit tests — perception: observation engine fuse, working memory TTL, face tracker,
frame sampler, face recognizer (insightface mocked — no model download).

refactor/agent-session-gemini: SpeechForwarder deleted (AgentSession handles audio
input). SpeechForwarder tests removed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np

from dto.observations import (
    CurrentContext,
    DeviceObservation,
    FaceObservation,
    SceneObservation,
    SpeechObservation,
)
from perception.face.recognizer import DetectedFace, FaceRecognizer
from perception.face.tracker import FaceTracker, Track
from perception.observation.engine import ObservationEngine, fuse
from perception.observation.working_memory import WorkingMemory
from perception.vision.sampler import FrameSampler, _encode_jpeg


class TestFuse:
    def test_mixed_batch(self) -> None:
        batch = [
            FaceObservation(person_id="p1", name="Asep", confidence=0.95, is_known=True),
            FaceObservation(person_id="p2", name="Asep", confidence=0.9, is_known=True),  # dup
            SceneObservation(location="apotek", activity="beli obat", confidence=0.8),
            SpeechObservation(transcript="apa ini?", confidence=0.9, is_final=True),
            DeviceObservation(battery_level=72, wifi_connected=True, confidence=1.0),
        ]
        ctx = fuse(batch)
        assert ctx.visible_people == ["Asep"]  # dedup
        assert ctx.scene == "apotek"
        assert ctx.activity == "beli obat"
        assert ctx.speech == "apa ini?"
        assert "baterai 72%" in ctx.device and "wifi on" in ctx.device
        assert 0.0 < ctx.confidence <= 1.0

    def test_unknown_face_surfaced(self) -> None:
        """Unknown faces surface as 'Orang tidak dikenali' so the agent can ask to register."""
        ctx = fuse([FaceObservation(confidence=0.5, is_known=False, embedding=None)])
        assert ctx.visible_people == ["Orang tidak dikenali"]

    def test_multiple_unknown_faces_deduped(self) -> None:
        """Multiple unknown faces in one window surface as a single 'Orang tidak dikenali'."""
        ctx = fuse(
            [
                FaceObservation(confidence=0.4, is_known=False, embedding=None),
                FaceObservation(confidence=0.3, is_known=False, embedding=None),
            ]
        )
        assert ctx.visible_people == ["Orang tidak dikenali"]

    def test_known_plus_unknown_surfaced(self) -> None:
        """Known person + unknown person both surface."""
        ctx = fuse(
            [
                FaceObservation(person_id="p1", name="Asep", confidence=0.9, is_known=True),
                FaceObservation(confidence=0.4, is_known=False, embedding=None),
            ]
        )
        assert ctx.visible_people == ["Asep", "Orang tidak dikenali"]

    def test_possible_match_surfaced_as_maybe(self) -> None:
        """FAISS possible match (0.35-0.50) surfaces as 'Mungkin <name>' not 'Orang tidak dikenali'."""
        ctx = fuse(
            [FaceObservation(person_id="p3", name="Budi", confidence=0.7, is_possible_match=True)]
        )
        assert ctx.visible_people == ["Mungkin Budi"]

    def test_possible_match_without_name_falls_back_to_unknown(self) -> None:
        """Possible match with no name resolved (graph down) → 'Orang tidak dikenali'."""
        ctx = fuse(
            [FaceObservation(person_id="p3", name=None, confidence=0.65, is_possible_match=True)]
        )
        assert ctx.visible_people == ["Orang tidak dikenali"]

    def test_known_plus_possible_plus_unknown(self) -> None:
        """All three tiers surface distinctly in one window."""
        ctx = fuse(
            [
                FaceObservation(person_id="p1", name="Asep", confidence=0.95, is_known=True),
                FaceObservation(
                    person_id="p2", name="Budi", confidence=0.7, is_possible_match=True
                ),
                FaceObservation(confidence=0.3, is_known=False, embedding=None),
            ]
        )
        assert ctx.visible_people == ["Asep", "Mungkin Budi", "Orang tidak dikenali"]

    def test_possible_match_deduped(self) -> None:
        """Two possible matches for the same name dedup to one 'Mungkin <name>'."""
        ctx = fuse(
            [
                FaceObservation(
                    person_id="p2", name="Budi", confidence=0.65, is_possible_match=True
                ),
                FaceObservation(
                    person_id="p2", name="Budi", confidence=0.7, is_possible_match=True
                ),
            ]
        )
        assert ctx.visible_people == ["Mungkin Budi"]

    def test_latest_scene_wins(self) -> None:
        ctx = fuse(
            [
                SceneObservation(location="rumah", confidence=0.8),
                SceneObservation(location="apotek", confidence=0.9),
            ]
        )
        assert ctx.scene == "apotek"

    def test_interim_speech_ignored(self) -> None:
        ctx = fuse([SpeechObservation(transcript="apa in", is_final=False)])
        assert ctx.speech is None

    def test_empty_batch(self) -> None:
        ctx = fuse([])
        assert ctx.confidence == 0.0 and ctx.visible_people == []


class TestWorkingMemory:
    def test_expiry(self) -> None:
        class C:
            t = 0.0

        wm = WorkingMemory(max_age_ms=100, _clock=lambda: C.t)
        assert wm.get() is None
        ctx = CurrentContext(visible_people=["Asep"])
        wm.set(ctx)
        C.t = 0.05
        assert wm.get() is not None
        C.t = 0.2
        assert wm.get() is None  # stale

    def test_age_ms(self) -> None:
        class C:
            t = 0.0

        wm = WorkingMemory(max_age_ms=100, _clock=lambda: C.t)
        assert wm.age_ms == float("inf")
        C.t = 1.0
        wm.set(CurrentContext())
        assert wm.age_ms == 0.0  # deterministic: no time elapsed between set + read


class TestObservationEngine:
    async def test_emit_fuses_to_working_memory(self) -> None:
        wm = WorkingMemory()
        engine = ObservationEngine(wm, window_ms=1)
        engine.start()
        await engine.emit(SceneObservation(location="apotek", confidence=0.9))
        await engine.emit(SpeechObservation(transcript="apa ini?", is_final=True))
        for _ in range(200):
            if wm.get() is not None:
                break
            await asyncio.sleep(0.005)
        await engine.stop()
        assert wm.get() is not None
        assert wm.get().scene == "apotek"

    async def test_stop_no_task_is_noop(self) -> None:
        engine = ObservationEngine(WorkingMemory())
        await engine.stop()  # never started

    async def test_start_twice_overwrites(self) -> None:
        wm = WorkingMemory()
        engine = ObservationEngine(wm, window_ms=1)
        engine.start()
        engine.start()  # second start replaces task
        await engine.emit(SceneObservation(location="rumah", confidence=0.8))
        for _ in range(200):
            if wm.get() is not None:
                break
            await asyncio.sleep(0.005)
        await engine.stop()


class TestFaceTracker:
    def _det(self, bbox, emb=None):
        return SimpleNamespace(bbox=bbox, embedding=emb or np.ones(4, dtype=np.float32))

    def test_same_bbox_same_track(self) -> None:
        tr = FaceTracker()
        r1 = tr.update([self._det((1, 1, 10, 10))])
        assert r1[0][0] == 0
        r2 = tr.update([self._det((1, 2, 10, 11))])  # overlapping
        assert r2[0][0] == 0
        assert tr.active_tracks[0].hit_count == 2

    def test_far_bbox_new_track(self) -> None:
        tr = FaceTracker()
        tr.update([self._det((1, 1, 10, 10))])
        r = tr.update([self._det((500, 500, 510, 510))])
        assert r[0][0] == 1

    def test_iou_zero_disjoint(self) -> None:
        tr = FaceTracker()
        r = tr.update([self._det((1, 1, 10, 10))])
        r2 = tr.update([self._det((20, 20, 30, 30))])
        assert r2[0][0] != r[0][0]

    def test_track_expires(self) -> None:
        class C:
            t = 0.0

        tr = FaceTracker(ttl_ms=100, _clock=lambda: C.t)
        tr.update([self._det((1, 1, 10, 10))])
        C.t = 0.2  # 200ms > 100ms ttl
        tr.update([])  # drop happens on update
        assert tr.active_tracks == []

    def test_stale_check(self) -> None:
        # Track stamps `now` at construction — use a fixed clock, not real monotonic.
        track = Track(0, (1, 1, 10, 10), None, now=0.0)
        assert track.stale(now=0.05, ttl_ms=100) is False
        assert track.stale(now=0.2, ttl_ms=100) is True


class TestFrameSampler:
    def _frame(self, w=2, h=2, byte=0):
        data = bytes([byte]) * (w * h * 4)  # BGRA
        convert = SimpleNamespace(data=data)
        return SimpleNamespace(
            convert=lambda kind: convert,
            height=h,
            width=w,
        )

    def _stream(self, frames):
        async def _gen():
            for f in frames:
                yield SimpleNamespace(frame=f)

        return _gen()

    async def test_yields_sampled_frames_high_fps(self) -> None:
        # Add small delays between frames so the monotonic clock advances past
        # the interval (fps=1000 → interval=0.001s). Without the delay, both
        # frames arrive at the same clock tick and the second is rate-limited.
        async def _delayed_stream():
            for f in [self._frame(byte=1), self._frame(byte=2)]:
                yield SimpleNamespace(frame=f)
                await asyncio.sleep(0.01)

        s = FrameSampler(_delayed_stream(), fps=1000.0)
        frames = [f async for f in s.frames()]
        assert len(frames) == 2
        assert frames[0]["frame_no"] == 1 and frames[1]["frame_no"] == 2
        assert frames[0]["bgr"].shape == (2, 2, 3)

    async def test_rate_limits_low_fps(self) -> None:
        s = FrameSampler(self._stream([self._frame(byte=1), self._frame(byte=2)]), fps=0.001)
        frames = [f async for f in s.frames()]
        assert len(frames) == 1  # second frame within interval → skipped

    def test_encode_jpeg_roundtrip(self) -> None:
        import cv2

        img = (np.random.default_rng(0).random((64, 64, 3)) * 255).astype(np.uint8)
        jpg = _encode_jpeg(img)
        dec = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        assert dec.shape == (64, 64, 3)


class TestFaceRecognizer:
    def _face(self, emb):
        return SimpleNamespace(
            normed_embedding=emb,
            bbox=np.array([1.2, 3.7, 10.4, 12.9]),
            det_score=0.98,
        )

    def test_detect_and_embed(self, monkeypatch) -> None:
        fake_app = SimpleNamespace(
            get=lambda img, max_num: [self._face(np.ones(512, dtype=np.float32))]
        )
        monkeypatch.setattr("perception.face.recognizer._load_app", lambda: fake_app)
        faces = FaceRecognizer().detect_and_embed(np.zeros((64, 64, 3), dtype=np.uint8))
        assert len(faces) == 1
        f = faces[0]
        assert isinstance(f, DetectedFace)
        assert f.embedding.shape == (512,)
        assert f.bbox == (1, 4, 10, 13)  # rounded to int
        assert f.det_score == 0.98

    def test_none_embedding_skipped(self, monkeypatch) -> None:
        fake_app = SimpleNamespace(
            get=lambda img, max_num: [self._face(None), self._face(np.ones(512, dtype=np.float32))]
        )
        monkeypatch.setattr("perception.face.recognizer._load_app", lambda: fake_app)
        faces = FaceRecognizer().detect_and_embed(np.zeros((64, 64, 3), dtype=np.uint8))
        assert len(faces) == 1

    def test_no_faces(self, monkeypatch) -> None:
        fake_app = SimpleNamespace(get=lambda img, max_num: [])
        monkeypatch.setattr("perception.face.recognizer._load_app", lambda: fake_app)
        assert FaceRecognizer().detect_and_embed(np.zeros((64, 64, 3), dtype=np.uint8)) == []
