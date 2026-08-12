"""Tunable thresholds + timing defaults.

Face thresholds: face_recognition.md §10 (>0.50 known, 0.35–0.50 possible, <0.35 unknown).
Timing: perception.md §11 (fusion 1s, observation TTL 5s, max context age 30s).
These mirror the Settings defaults in packages/config/env/settings.py but live here as
plain module constants for pure-Python use (shared has no settings dep).
"""

from __future__ import annotations

# Face identity — cosine similarity over L2-normalized 512-d embeddings.
FACE_KNOWN_THRESHOLD = 0.50  # >= → confirmed/known person
FACE_POSSIBLE_THRESHOLD = 0.35  # >= → possible match; below → unknown

# Observation engine timing (milliseconds).
FUSION_WINDOW_MS = 1000
OBSERVATION_TTL_MS = 5000
MAX_CONTEXT_AGE_MS = 30000

# Perception cadence.
FRAME_SAMPLE_FPS = 1.0

# Reasoning audio (Gemini Live output).
GEMINI_AUDIO_SAMPLE_RATE = 24000
GEMINI_AUDIO_CHANNELS = 1

# Embedding dims (InsightFace buffalo_l).
FACE_EMBEDDING_DIM = 512
