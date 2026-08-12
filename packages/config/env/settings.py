"""Central settings for Memora.

Single source of truth. Required fields (no default) raise at import if missing
so a misconfigured deploy fails loudly at startup, not mid-request.
"""

from __future__ import annotations

import socket
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App config loaded from env / .env.

    Required (no default → startup fails with a clear ValidationError listing
    what's missing): LIVEKIT_*, GEMINI_API_KEY, DATABASE_URL, NEO4J_*.
    Optional/tunable carry sane defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # === LiveKit (required) ===
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str

    # === Gemini (required) ===
    gemini_api_key: str
    gemini_live_model: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    gemini_text_model: str = "gemini-2.5-flash"

    # === Postgres (required) ===
    database_url: str

    @field_validator("database_url")
    @classmethod
    def _ensure_asyncpg_driver(cls, v: str) -> str:
        """docker-compose injects postgresql:// (asyncpg). Normalize to +asyncpg
        so SQLAlchemy create_async_engine works without callers rewriting the URL."""
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    # === Neo4j (required) ===
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    # === FAISS ===
    faiss_index_path: str = "data/face_index.faiss"
    face_embedding_dim: int = 512
    face_match_threshold: float = 0.50
    face_possible_match_threshold: float = 0.35

    # === InsightFace ===
    face_model_root: str = "models/insightface"

    # === Perception ===
    # ponytail: 0.5 FPS (every 2s) — InsightFace ONNX runtime leaks ~20MB/frame on CPU.
    # 1 FPS fills 1.8GB in 80s and gets killed. 0.5 FPS gives ~4 min before OOM.
    # Fix: use a separate process for face detection, or switch to a lighter model.
    frame_sample_fps: float = 0.5
    observation_fusion_window_ms: int = 1000
    observation_ttl_ms: int = 5000
    max_context_age_ms: int = 30000

    # === Reasoning ===
    gemini_audio_output_sample_rate: int = 24000
    gemini_audio_output_channels: int = 1

    # === Server ===
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    # === Worker health check ===
    worker_health_port: int = 8001

    # === Agent identity ===
    # Derived from hostname so each machine gets a unique agent name — prevents
    # dispatch cross-routing when multiple developers share a LiveKit Cloud account.
    # Override with AGENT_NAME env if you want a fixed custom name.
    agent_name: str = f"memora-agent-{socket.gethostname().split('.')[0]}"

    # === Locale ===
    # IANA tz for local-day windows (reminders, schedules). Indonesia is UTC+7.
    local_timezone: str = "Asia/Jakarta"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton. Importing this raises if required env vars are missing."""
    return Settings()
