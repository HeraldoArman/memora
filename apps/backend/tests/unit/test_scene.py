"""Unit tests — scene understanding: SceneUnderstander parse + failure paths.

No live API: genai.Client is mocked. Verifies structured output parsing + graceful
degradation when the API fails.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from perception.scene.understander import SceneUnderstander, _normalize, _parse


class TestParse:
    def test_parsed_dict(self) -> None:
        fake = type(
            "R",
            (),
            {
                "parsed": {
                    "location": "apotek",
                    "objects": ["obat"],
                    "activity": "beli obat",
                    "confidence": 0.9,
                },
                "text": "",
            },
        )()
        data = _parse(fake)
        assert data["location"] == "apotek"
        assert data["objects"] == ["obat"]
        assert data["activity"] == "beli obat"
        assert data["confidence"] == 0.9

    def test_text_fallback(self) -> None:
        fake = type(
            "R",
            (),
            {
                "parsed": None,
                "text": json.dumps({"location": "rumah", "objects": [], "activity": "istirahat"}),
            },
        )()
        data = _parse(fake)
        assert data["location"] == "rumah"
        assert data["activity"] == "istirahat"

    def test_empty_text(self) -> None:
        fake = type("R", (), {"parsed": None, "text": ""})()
        assert _parse(fake) is None

    def test_bad_json(self) -> None:
        fake = type("R", (), {"parsed": None, "text": "not json"})()
        assert _parse(fake) is None


class TestNormalize:
    def test_missing_fields(self) -> None:
        data = _normalize({"location": "apotek"})
        assert data["location"] == "apotek"
        assert data["objects"] == []
        assert data["activity"] is None
        assert data["confidence"] == 0.8  # default


class TestSceneUnderstander:
    async def test_empty_jpeg_returns_none(self) -> None:
        su = SceneUnderstander(client=object())
        assert await su.understand(b"") is None

    async def test_api_failure_returns_none(self) -> None:
        client = MagicMock()
        client.models.generate_content = MagicMock(side_effect=RuntimeError("api down"))
        su = SceneUnderstander(client=client)
        assert await su.understand(b"jpeg") is None

    async def test_happy_path(self) -> None:
        resp = type(
            "R",
            (),
            {
                "parsed": {
                    "location": "apotek",
                    "objects": ["obat"],
                    "activity": "beli obat",
                    "confidence": 0.9,
                },
                "text": "",
            },
        )()
        client = MagicMock()
        client.models.generate_content = MagicMock(return_value=resp)
        su = SceneUnderstander(client=client)
        data = await su.understand(b"jpeg")
        assert data["location"] == "apotek"
        assert data["activity"] == "beli obat"
        assert data["confidence"] == 0.9
