"""Summarizer — compress context over the token budget via non-live Gemini.

context.md §13 (summarization): when the retrieved context exceeds the reasoning model's
context window, compress older/less-relevant memories into a summary. Uses generate_content
(not the live session) — summarization is offline batch work, never on the realtime path.

Ponytail: a single character-budget gate — if the assembled text fits, skip the API call
entirely (most turns are short). Only call Gemini when genuinely over budget.
"""

from __future__ import annotations

import logging

from env import get_settings

from prompts import SUMMARIZATION_PROMPT

logger = logging.getLogger(__name__)

# Soft character budget for the context package text (~4 chars/token, conservative for Bahasa).
_DEFAULT_CHAR_BUDGET = 6000


class Summarizer:
    """Compress context text when it exceeds the character budget."""

    def __init__(self, client=None, *, char_budget: int = _DEFAULT_CHAR_BUDGET) -> None:
        self._client = client
        self.char_budget = char_budget

    def _get_client(self):
        if self._client is not None:
            return self._client
        from google import genai

        settings = get_settings()
        self._client = genai.Client(api_key=settings.gemini_api_key)
        return self._client

    def needs_summary(self, text: str) -> bool:
        return len(text) > self.char_budget

    async def summarize(self, text: str) -> str:
        """Return a compressed summary of `text`, or the original if under budget / on failure."""
        if not self.needs_summary(text):
            return text
        try:
            client = self._get_client()
            settings = get_settings()
            resp = await client.aio.models.generate_content(
                model=settings.gemini_text_model,
                contents=SUMMARIZATION_PROMPT.format(content=text),
            )
            summary = getattr(resp, "text", None) or ""
            return summary.strip() or text
        except Exception as e:  # noqa: BLE001
            logger.warning("summarization failed, returning truncated text: %s", e)
            # graceful degradation: truncate to budget rather than drop the context
            return text[: self.char_budget]


# --- self-check (no API): budget gate + truncation fallback ---
def _self_check() -> None:  # pragma: no cover
    s = Summarizer(client=object(), char_budget=100)  # client unused when under budget
    assert not s.needs_summary("short")
    assert s.needs_summary("x" * 200)

    import asyncio
    from unittest.mock import AsyncMock

    s2 = Summarizer(char_budget=10)
    # failing client → graceful truncation
    bad = AsyncMock()
    bad.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("no key"))
    s2._client = bad
    out = asyncio.run(s2.summarize("a very long text that exceeds the budget"))
    assert out == "a very long text that exceeds the budget"[:10], out
    print(f"summarizer self-check OK: budget={s2.char_budget}")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
