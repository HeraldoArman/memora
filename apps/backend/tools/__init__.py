"""Tool layer — Gemini Live function-declaration surface + dispatch.

build_registry() assembles the name→callable map; the reasoning router calls
get_tool(name) to dispatch live tool_call events. Schemas (function declarations
for LiveConnectConfig) live in packages.shared.schemas.tools.
"""

from tools.registry import ToolContext, build_registry, get_tool

__all__ = ["ToolContext", "build_registry", "get_tool"]
