"""Pipeline — extraction→consolidation orchestration.

runner.PipelineRunner is the entry point; filter gates, consolidator writes through repos.
"""

from __future__ import annotations

from pipeline.consolidator import Consolidator
from pipeline.filter import should_extract
from pipeline.runner import PipelineRunner

__all__ = ["Consolidator", "PipelineRunner", "should_extract"]
