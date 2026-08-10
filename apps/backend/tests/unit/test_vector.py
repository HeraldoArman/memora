"""Unit tests — FAISS layer (packages/database/vector): embeddings, index, repository.

Real FAISS in-memory + a tmpfile for save/load — no DB, no network.
"""

from __future__ import annotations

import numpy as np
import pytest
from vector.embeddings import l2_normalize
from vector.index import FaceIndex
from vector.repository import FaceLookup, FaceRepository


class TestL2Normalize:
    def test_single_vector(self) -> None:
        v = l2_normalize(np.array([3.0, 4.0]))
        assert np.allclose(np.linalg.norm(v), 1.0)

    def test_zero_vector_unchanged(self) -> None:
        v = l2_normalize(np.zeros(4, dtype=np.float32))
        assert np.allclose(v, 0)

    def test_batch(self) -> None:
        batch = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0], [6.0, 8.0]]))
        assert np.allclose(np.linalg.norm(batch, axis=1), [1.0, 0.0, 1.0])


class TestFaceIndex:
    def _idx(self) -> FaceIndex:
        return FaceIndex(dim=4)

    def test_empty_size(self) -> None:
        assert self._idx().size == 0

    def test_add_and_search(self) -> None:
        idx = self._idx()
        idx.add(np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], dtype=np.float32))
        assert idx.size == 2
        scores, ids = idx.search(np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32), k=1)
        assert int(ids[0]) == 0
        assert float(scores[0]) == pytest.approx(0.9, abs=1e-3)

    def test_add_wrong_dim_raises(self) -> None:
        with pytest.raises(ValueError):
            self._idx().add(np.ones((1, 3), dtype=np.float32))

    def test_add_1d_vector(self) -> None:
        idx = self._idx()
        idx.add(np.ones(4, dtype=np.float32))
        assert idx.size == 1

    def test_save_load(self, tmp_path) -> None:
        idx = self._idx()
        idx.add(np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32))
        path = tmp_path / "idx.faiss"
        idx.save(path)
        loaded = FaceIndex.load(path, dim=4)
        assert loaded.size == 1
        scores, ids = loaded.search(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32))
        assert int(ids[0]) == 0 and float(scores[0]) > 0.99

    def test_load_missing_path_returns_empty(self, tmp_path) -> None:
        loaded = FaceIndex.load(tmp_path / "nope.faiss", dim=4)
        assert loaded.size == 0


class TestFaceRepository:
    def _repo(self, *, known=0.80, possible=0.60) -> FaceRepository:
        return FaceRepository(
            FaceIndex(dim=8),
            known_threshold=known,
            possible_threshold=possible,
        )

    def _vec(self, seed: int) -> np.ndarray:
        rng = np.random.default_rng(seed)
        v = rng.normal(size=8).astype(np.float32)
        return v / np.linalg.norm(v)

    def test_register_returns_row_id(self) -> None:
        r = self._repo()
        assert r.register(self._vec(1), "p1") == 0
        assert r.register(self._vec(2), "p2") == 1
        assert r.size == 2 and r.person_ids == ["p1", "p2"]

    def test_lookup_empty(self) -> None:
        hit = self._repo().lookup(self._vec(1))
        assert hit.person_id is None and not hit.is_known and hit.score == 0.0

    def test_lookup_known(self) -> None:
        r = self._repo()
        v = self._vec(1)
        r.register(v, "p1")
        hit = r.lookup(v)
        assert hit.is_known and hit.person_id == "p1"

    def test_lookup_possible(self) -> None:
        r = self._repo(known=0.95, possible=0.80)
        # explicit unit vectors with dot product = 0.9 → in the possible band
        v1 = np.zeros(8, dtype=np.float32)
        v1[0] = 1.0
        v2 = np.zeros(8, dtype=np.float32)
        v2[0] = 0.9
        v2[1] = np.sqrt(1 - 0.81)
        r.register(v1, "p1")
        hit = r.lookup(v2)
        assert hit.score == pytest.approx(0.9, abs=1e-3)
        assert hit.is_possible and not hit.is_known
        assert hit.person_id == "p1"

    def test_lookup_unknown(self) -> None:
        r = self._repo()
        r.register(self._vec(1), "p1")
        far = np.zeros(8, dtype=np.float32)
        far[0] = 1.0  # orthogonal-ish to v1
        hit = r.lookup(far)
        assert not hit.is_known and not hit.is_possible and hit.person_id is None

    def test_lookup_custom_thresholds(self) -> None:
        r = self._repo(known=0.10, possible=0.05)
        r.register(self._vec(1), "p1")
        hit = r.lookup(self._vec(2))
        assert hit.is_known  # everything above 0.10

    def test_save_load_round_trip(self, tmp_path) -> None:
        r = self._repo()
        v = self._vec(1)
        r.register(v, "person-7")
        path = str(tmp_path / "face_index.faiss")
        r.save(path)
        loaded = FaceRepository.load(path)
        assert loaded.size == 1 and loaded.person_ids == ["person-7"]
        hit = loaded.lookup(v)
        assert hit.is_known and hit.person_id == "person-7"

    def test_load_missing_sidecar(self, tmp_path) -> None:
        r = self._repo()
        v = self._vec(1)
        r.register(v, "p1")
        path = str(tmp_path / "face_index.faiss")
        r.save(path)
        # drop the sidecar → mapping lost, index retained
        from pathlib import Path

        Path(path + ".sidecar.json").unlink()
        loaded = FaceRepository.load(path)
        assert loaded.size == 1 and loaded.person_ids == []


class TestFaceLookup:
    def test_repr(self) -> None:
        assert "known=True" in repr(FaceLookup("p1", 0.9, True, False))
