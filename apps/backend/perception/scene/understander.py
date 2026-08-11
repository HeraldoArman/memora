"""Scene understander — Gemini Vision analyzes frames for location/objects/activity.

perception.md §A.4.2: Gemini Vision analyzes the surrounding environment. Runs at ~1 FPS
alongside the face identity path. Uses non-live generate_content (like the extractor) so
the live session stays focused on reasoning + audio. Output → SceneObservation → ObservationEngine.
"""

from __future__ import annotations

import logging

from env import get_settings

from prompts import SCENE_PROMPT
from schemas import SCENE_SCHEMA

log = logging.getLogger(__name__)


class SceneUnderstander:
    """Analyze a JPEG frame via Gemini Vision → {location, objects, activity}."""

    def __init__(self, client=None) -> None:
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        from google import genai

        self._client = genai.Client(api_key=get_settings().gemini_api_key)
        return self._client

    async def understand(self, jpeg: bytes) -> dict | None:
        """Return {location, objects, activity, confidence} from a JPEG frame.

        Empty input or API failure → None (no SceneObservation emitted).
        """
        if not jpeg:
            return None
        from google.genai import types

        settings = get_settings()
        try:
            client = self._get_client()
            resp = await client.aio.models.generate_content(
                model=settings.gemini_text_model,
                contents=[
                    types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"),
                    SCENE_PROMPT,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=SCENE_SCHEMA,
                ),
            )
            result = _parse(resp)
            del resp
            return result
        except Exception as e:  # noqa: BLE001
            log.warning("scene understanding failed: %s", e)
            return None


def _parse(resp) -> dict | None:
    """Normalize a GenerateContentResponse into our dict."""
    import json

    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, dict):
        return _normalize(parsed)
    text = getattr(resp, "text", None) or ""
    if not text.strip():
        return None
    try:
        return _normalize(json.loads(text))
    except (json.JSONDecodeError, ValueError):
        return None


def _normalize(data: dict) -> dict:
    return {
        "location": data.get("location") or None,
        "objects": data.get("objects") or [],
        "activity": data.get("activity") or None,
        "confidence": float(data.get("confidence", 0.8) or 0.8),
    }


# --- self-check (no API): parse shape ---
def _self_check() -> None:  # pragma: no cover
    import json

    fake = type(
        "R",
        (),
        {
            "text": json.dumps(
                {
                    "location": "apotek",
                    "objects": ["obat", "rak"],
                    "activity": "beli obat",
                    "confidence": 0.9,
                }
            ),
            "parsed": None,
        },
    )()
    data = _parse(fake)
    assert data["location"] == "apotek", data
    assert data["objects"] == ["obat", "rak"], data
    assert data["activity"] == "beli obat", data

    # empty input → None (no API call)
    import asyncio

    assert asyncio.run(SceneUnderstander(client=object()).understand(b"")) is None
    print("scene understander self-check OK: parse + empty guard")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
