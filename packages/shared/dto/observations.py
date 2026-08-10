"""Perception-layer DTOs — observations + the fused CurrentContext.

perception.md §11: Observation Engine fuses a 1s window of Face/Scene/Speech/Device
observations into a single CurrentContext, which feeds the Context Engine and Reasoning.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from constants import ObservationSource
from utils import gen_id, now_utc


class Observation(BaseModel):
    """Common observation envelope. payload varies by source (discriminated subclass)."""

    observation_id: str = Field(default_factory=gen_id)
    timestamp: datetime = Field(default_factory=now_utc)
    source: ObservationSource
    confidence: float = 0.0

    model_config = {"arbitrary_types_allowed": True}


class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class FaceObservation(Observation):
    """face_recognition.md §10 identity resolution output."""

    source: ObservationSource = ObservationSource.FACE_RECOGNITION
    person_id: str | None = None  # None = unknown/unmatched
    name: str | None = None
    confidence: float = 0.0
    bounding_box: BoundingBox | None = None
    embedding_id: int | None = None  # FAISS row id
    is_known: bool = False
    is_possible_match: bool = False
    # Raw 512-d embedding, retained so search_person_by_face can re-identify the
    # currently visible person from Working Memory without re-running the recognizer.
    # arbitrary_types_allowed is set on Observation; numpy ndarray is accepted here.
    embedding: object | None = None


class SceneObservation(Observation):
    """Gemini scene understanding: location, objects, activity."""

    source: ObservationSource = ObservationSource.SCENE_UNDERSTANDING
    location: str | None = None
    objects: list[str] = Field(default_factory=list)
    activity: str | None = None


class SpeechObservation(Observation):
    """Gemini Live input_audio_transcription (free STT). interim or final."""

    source: ObservationSource = ObservationSource.SPEECH_RECOGNITION
    speaker: str | None = None
    transcript: str
    language: str = "id"  # Bahasa Indonesia default
    is_final: bool = True


class DeviceObservation(Observation):
    """Device telemetry via LiveKit data channel."""

    source: ObservationSource = ObservationSource.DEVICE_EVENTS
    battery_level: float | None = None  # 0-100
    button_pressed: bool = False
    wifi_connected: bool = True


class CurrentContext(BaseModel):
    """Fused 1s-window context — perception.md §11 output. Feeds Context Engine."""

    timestamp: datetime = Field(default_factory=now_utc)
    visible_people: list[str] = Field(default_factory=list)
    scene: str | None = None
    activity: str | None = None
    speech: str | None = None
    device: str | None = None
    confidence: float = 0.0
    # Raw observations retained for provenance/debug.
    observations: list[Observation] = Field(default_factory=list)
