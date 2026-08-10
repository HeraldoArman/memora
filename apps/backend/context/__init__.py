"""Context layer — retrieval, ranking, summarization, packaging.

ContextEngine.build() is the entry point: retrieve→rank→package→summarize→(text).
"""

from __future__ import annotations

from context.engine import ContextEngine
from context.packager import package, to_text
from context.summarizer import Summarizer

__all__ = ["ContextEngine", "Summarizer", "package", "to_text"]
