"""Offline face-recognition test — static image folders → register → lookup.

Validates the recognition core (FaceRecognizer + FAISS thresholds) against any
folder-per-person image dataset. No LiveKit / DB / Neo4j needed — in-memory index.

    uv run python scripts/verify/face_dataset.py /tmp/memora_face_dataset --people 8 --per-person 6

Report = score distributions (same-person vs cross-person) + threshold verdict, so the
0.80/0.60 known/possible cutoffs can be sanity-checked against real buffalo_l embeddings.
A person folder is any dir named pins_<Name> (Kaggle/HF shape) or a dir of images.
"""

from __future__ import annotations

import argparse
import pathlib
import statistics
import sys

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from env import get_settings  # noqa: E402
from vector import repository as vector_repo  # noqa: E402

from perception.face.recognizer import FaceRecognizer  # noqa: E402

IMG_EXT = (".jpg", ".jpeg", ".png")


def person_dirs(root: pathlib.Path) -> list[tuple[str, list[pathlib.Path]]]:
    """Group images by person. Label = nearest ancestor dir starting with 'pins_'
    (celebrity datasets) else the image's parent dir name (your own photo folders)."""
    people: dict[str, list[pathlib.Path]] = {}
    for p in root.rglob("*"):
        if p.suffix.lower() not in IMG_EXT:
            continue
        label = p.parent.name
        for anc in p.parents:
            if anc.name.startswith("pins_"):
                label = anc.name[len("pins_") :]
                break
        people.setdefault(label, []).append(p)
    return sorted(people.items())


def load_bgr(path: pathlib.Path) -> np.ndarray | None:
    img = cv2.imread(str(path))
    return img if img is not None else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=pathlib.Path)
    ap.add_argument("--people", type=int, default=8, help="max people to test")
    ap.add_argument("--per-person", type=int, default=6, help="images used per person")
    ap.add_argument(
        "--register", type=int, default=3, help="first N images registered, rest tested"
    )
    args = ap.parse_args()

    settings = get_settings()
    face_repo = vector_repo.FaceRepository(
        vector_repo.FaceIndex(settings.face_embedding_dim),
        known_threshold=settings.face_match_threshold,
        possible_threshold=settings.face_possible_match_threshold,
    )
    rec = FaceRecognizer()
    people = person_dirs(args.root)
    if not people:
        sys.exit(f"no images under {args.root}")

    tested: list[tuple[str, float]] = []  # (true_person, top-score vs registered)
    cross_scores: list[float] = []  # wrong-person top scores
    no_face = 0
    reg_people: set[str] = set()

    for name, imgs in people[: args.people]:
        imgs = imgs[: args.per_person]
        if len(imgs) < 2:
            continue
        reg_people.add(name)
        reg, test = imgs[: args.register], imgs[args.register :]
        for p in reg:
            emb = _embed(rec, p)
            if emb is None:
                no_face += 1
                continue
            face_repo.register(emb, name)
        for p in test:
            emb = _embed(rec, p)
            if emb is None:
                no_face += 1
                continue
            hit = face_repo.lookup(emb)
            if hit.person_id == name:
                tested.append((name, hit.score))
            else:
                cross_scores.append(hit.score)

    if not tested:
        print("no test faces resolved — dataset too small or faces not detected")
        return

    same = [s for _, s in tested]
    print(f"people registered: {len(reg_people)}  images no-face: {no_face}")
    print(
        f"\nsame-person matches: {len(tested)}/{len(same)}  "
        f"score min/med/max = {min(same):.3f}/{statistics.median(same):.3f}/{max(same):.3f}"
    )
    hits_known = sum(1 for s in same if s >= settings.face_match_threshold)
    hits_possible = sum(1 for s in same if s >= settings.face_possible_match_threshold)
    print(
        f"  >= {settings.face_match_threshold:.2f} (known): {hits_known}/{len(same)}  "
        f">= {settings.face_possible_match_threshold:.2f} (possible+): {hits_possible}/{len(same)}"
    )

    if cross_scores:
        print(f"\ncross-person (wrong person) top scores: {len(cross_scores)}")
        print(
            f"  score min/med/max = {min(cross_scores):.3f}/{statistics.median(cross_scores):.3f}/{max(cross_scores):.3f}"
        )
        false_pos = sum(1 for s in cross_scores if s >= settings.face_possible_match_threshold)
        false_known = sum(1 for s in cross_scores if s >= settings.face_match_threshold)
        print(
            f"  would-be 'possible' (>= {settings.face_possible_match_threshold:.2f}): {false_pos}  "
            f"'known' (>= {settings.face_match_threshold:.2f}): {false_known}"
        )

    print(
        "\nverdict: thresholds sane if same-median >= known-threshold and cross-max < possible-threshold"
    )


def _embed(rec, path: pathlib.Path) -> np.ndarray | None:
    """First detected face's embedding, else None."""
    img = load_bgr(path)
    if img is None:
        return None
    faces = rec.detect_and_embed(img)
    return faces[0].embedding if faces else None


if __name__ == "__main__":
    main()
