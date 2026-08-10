"""Face tracker — cross-frame identity continuity.

When the recognizer sees a face, we want the same track_id across consecutive frames even
before FAISS resolves identity. Simple IoU-based bbox association (no Kalman filter —
ponytail: 1 FPS means motion between frames is small; bbox overlap is enough for the
hackathon). Tracks expire after `ttl_ms` of no match.
"""

from __future__ import annotations

import time


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1, (bx2 - bx1) * (by2 - by1))
    return inter / (area_a + area_b - inter)


class Track:
    """One tracked face across frames."""

    __slots__ = ("track_id", "bbox", "embedding", "last_seen", "hit_count")

    def __init__(self, track_id: int, bbox, embedding, *, now: float) -> None:
        self.track_id = track_id
        self.bbox = bbox
        self.embedding = embedding
        self.last_seen = now
        self.hit_count = 1

    def stale(self, now: float, ttl_ms: int) -> bool:
        return (now - self.last_seen) * 1000 > ttl_ms


class FaceTracker:
    """Assign stable track_ids to detected faces via bbox IoU.

    max_iou: minimum overlap to associate. ttl_ms: drop tracks unseen this long.
    """

    def __init__(self, *, max_iou: float = 0.30, ttl_ms: int = 3000, _clock=time.monotonic) -> None:
        self.max_iou = max_iou
        self.ttl_ms = ttl_ms
        self._clock = _clock
        self._tracks: list[Track] = []
        self._next_id = 0

    def update(self, detections: list) -> list[tuple[int, object]]:
        """Match detections to tracks. Returns [(track_id, detection), ...].

        Each detection must have .bbox and .embedding (e.g. DetectedFace).
        """
        now = self._clock()
        self._drop_stale(now)
        assigned: list[tuple[int, object]] = []
        used_tracks: set[int] = set()

        # Greedy best-IoU match (ponytail: Hungarian overkill for ≤few faces/frame).
        for det in detections:
            best_id, best_iou = -1, self.max_iou
            for t in self._tracks:
                if t.track_id in used_tracks:
                    continue
                iou = _iou(t.bbox, det.bbox)
                if iou > best_iou:
                    best_iou, best_id = iou, t.track_id
            if best_id >= 0:
                t = next(t for t in self._tracks if t.track_id == best_id)
                t.bbox = det.bbox
                t.embedding = det.embedding
                t.last_seen = now
                t.hit_count += 1
                used_tracks.add(best_id)
                assigned.append((best_id, det))
            else:
                tid = self._next_id
                self._next_id += 1
                self._tracks.append(Track(tid, det.bbox, det.embedding, now=now))
                assigned.append((tid, det))
        return assigned

    @property
    def active_tracks(self) -> list[Track]:
        return list(self._tracks)

    def _drop_stale(self, now: float) -> None:
        self._tracks = [t for t in self._tracks if not t.stale(now, self.ttl_ms)]


# --- self-check ---
def _self_check() -> None:  # pragma: no cover
    from dataclasses import dataclass

    @dataclass
    class D:
        bbox: tuple
        embedding: object = None

    tr = FaceTracker()
    a1 = [(1, 1, 10, 10)]  # track 0
    r1 = tr.update([D(a1[0])])
    assert r1[0][0] == 0, r1
    # same bbox next frame → same track
    r2 = tr.update([D((1, 2, 10, 11))])
    assert r2[0][0] == 0, r2
    # far bbox → new track
    r3 = tr.update([D((500, 500, 510, 510))])
    assert r3[0][0] == 1, r3
    print(f"tracker self-check OK: tracks={len(tr.active_tracks)}")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
