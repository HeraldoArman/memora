"""Unit tests — env Settings (packages/config/env): validation + defaults + cache."""

from __future__ import annotations

import pytest
from env import Settings, get_settings
from pydantic import ValidationError


class TestSettingsValidation:
    def test_required_fields_missing(self, monkeypatch) -> None:
        for key in (
            "LIVEKIT_URL",
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
            "GEMINI_API_KEY",
            "DATABASE_URL",
            "NEO4J_URI",
            "NEO4J_USER",
            "NEO4J_PASSWORD",
        ):
            monkeypatch.delenv(key, raising=False)
        with pytest.raises(ValidationError):
            Settings()

    def test_required_fields_present(self, monkeypatch) -> None:
        monkeypatch.setenv("LIVEKIT_URL", "wss://x")
        monkeypatch.setenv("LIVEKIT_API_KEY", "k")
        monkeypatch.setenv("LIVEKIT_API_SECRET", "s")
        monkeypatch.setenv("GEMINI_API_KEY", "g")
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/db")
        monkeypatch.setenv("NEO4J_URI", "bolt://h:7687")
        monkeypatch.setenv("NEO4J_USER", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "pw")
        s = Settings()
        assert s.livekit_url == "wss://x"

    def test_database_url_normalized_to_asyncpg(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/db")
        s = Settings()
        assert s.database_url.startswith("postgresql+asyncpg://")

    def test_already_asyncpg_left_alone(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
        assert Settings().database_url == "postgresql+asyncpg://u:p@h/db"


class TestSettingsDefaults:
    def test_defaults(self, settings) -> None:
        assert settings.face_embedding_dim == 512
        assert settings.face_match_threshold == 0.50
        assert settings.face_possible_match_threshold == 0.35
        assert settings.observation_fusion_window_ms == 1000
        assert settings.observation_ttl_ms == 5000
        assert settings.max_context_age_ms == 30000
        assert settings.frame_sample_fps == 1.0
        assert settings.gemini_audio_output_sample_rate == 24000
        assert settings.gemini_audio_output_channels == 1
        assert settings.gemini_live_model == "gemini-2.0-flash-exp"
        assert settings.port == 8000 and settings.log_level == "INFO"

    def test_get_settings_cached(self, settings) -> None:
        assert get_settings() is settings


class TestGetSettingsEnvDriven:
    def test_live_model_env_override(self, monkeypatch) -> None:
        monkeypatch.setenv("GEMINI_LIVE_MODEL", "gemini-3.0-pro-live")
        get_settings.cache_clear()
        try:
            assert get_settings().gemini_live_model == "gemini-3.0-pro-live"
        finally:
            get_settings.cache_clear()
