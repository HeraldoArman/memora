"""Extraction layer — Gemini structured output + rule-first post-processing.

Pipeline stages: extractor (LLM) → normalizer → resolver → classifier → verifier.
The consolidator (writes through repos) lives in pipeline/, not here — extraction only
produces validated ExtractedKnowledge, it does not touch the stores.
"""

from __future__ import annotations

from extraction.classifier import classify, for_graph
from extraction.extractor import KnowledgeExtractor
from extraction.normalizer import normalize
from extraction.resolver import is_alias, resolve_batch, resolve_name
from extraction.verifier import accepted, verify

__all__ = [
    "KnowledgeExtractor",
    "accepted",
    "classify",
    "for_graph",
    "is_alias",
    "normalize",
    "resolve_batch",
    "resolve_name",
    "verify",
]
