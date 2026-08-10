"""Tool-layer DTOs — request/response for Gemini Live function calling.

tool_api.md: request schema {"tool": "...", "parameters": {...}}; response via
send_tool_response(FunctionResponse(id, response={...})).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from constants import ToolName
from utils import gen_id


class ToolRequest(BaseModel):
    """A tool/function call from the model. `name` + `parameters` dict."""

    call_id: str = Field(default_factory=gen_id)  # matches Gemini tool_call.id for response pairing
    name: ToolName
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolError(BaseModel):
    code: str  # e.g. "not_found", "bad_input", "service_unavailable"
    message: str


class ToolResponse(BaseModel):
    """Result returned to the model via send_tool_response."""

    call_id: str
    ok: bool = True
    result: dict[str, Any] = Field(default_factory=dict)
    error: ToolError | None = None
