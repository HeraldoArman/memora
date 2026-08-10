"""Knowledge extractor — Gemini structured output over a CurrentContext snapshot.

knowledge_extraction.md: non-live generate_content (NOT the live session) extracts
entities/relationships/facts from conversation text. Rule-first classification + resolution
runs after (normalizer.py, resolver.py, classifier.py); the LLM only does the hard NLU part.
Falls back to an empty result if the API is unavailable (graceful degradation).
"""

from __future__ import annotations

import json
import logging

from env import get_settings

from prompts import EXTRACTION_PROMPT
from schemas import EXTRACTION_SCHEMA

logger = logging.getLogger(__name__)


class KnowledgeExtractor:
    """Extract structured knowledge from text via Gemini generate_content."""

    def __init__(self, client=None) -> None:
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        from google import genai

        settings = get_settings()
        self._client = genai.Client(api_key=settings.gemini_api_key)
        return self._client

    async def extract(self, content: str) -> dict:
        """Return {entities, relationships, facts, confidence} from `content`.

        Empty/whitespace content → empty extraction (no API call).
        On API failure → empty extraction (logged), so the pipeline keeps running.
        """
        if not content or not content.strip():
            return _empty()
        from google.genai import types

        settings = get_settings()
        prompt = EXTRACTION_PROMPT.format(content=content)
        try:
            client = self._get_client()
            resp = await client.aio.models.generate_content(
                model=settings.gemini_text_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=EXTRACTION_SCHEMA,
                ),
            )
            data = _parse(resp)
            return data
        except Exception as e:  # noqa: BLE001
            logger.warning("extraction failed, returning empty: %s", e)
            return _empty()

    # --- self-check (no API): parse shape ---
    def _self_check(self) -> None:  # pragma: no cover
        fake = type(
            "R",
            (),
            {
                "text": json.dumps(
                    {
                        "entities": [{"name": "Asep", "category": "Person"}],
                        "relationships": [],
                        "facts": ["Asep is here"],
                        "confidence": 0.9,
                    }
                ),
                "parsed": None,
            },
        )()
        data = _parse(fake)
        assert data["entities"][0]["name"] == "Asep"
        assert data["facts"] == ["Asep is here"]
        # empty content → empty result, no API call
        import asyncio

        assert asyncio.run(self.extract("   ")) == _empty()
        print(f"extractor self-check OK: parsed {len(data['entities'])} entities")


def _parse(resp) -> dict:
    """Normalize a GenerateContentResponse into our dict. Prefer .parsed, fall back to .text."""
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, dict):
        return _normalize(parsed)
    text = getattr(resp, "text", None) or ""
    if not text.strip():
        return _empty()
    return _normalize(json.loads(text))


def _normalize(data: dict) -> dict:
    return {
        "entities": data.get("entities", []) or [],
        "relationships": data.get("relationships", []) or [],
        "facts": data.get("facts", []) or [],
        "confidence": float(data.get("confidence", 0.0) or 0.0),
    }


def _empty() -> dict:
    return {"entities": [], "relationships": [], "facts": [], "confidence": 0.0}


if __name__ == "__main__":  # pragma: no cover
    KnowledgeExtractor()._self_check()
