"""SSE event payloads for the streaming chat endpoint.

Seven events (HITL `tool_approval_required` intentionally dropped — no HITL in
this iteration): message_start, token, tool_start, tool_end, message_end,
error, done.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SSEMessageStart(BaseModel):
    type: Literal["message_start"] = "message_start"
    message_id: str
    conversation_id: str


class SSEToken(BaseModel):
    type: Literal["token"] = "token"
    delta: str


class SSEToolStart(BaseModel):
    type: Literal["tool_start"] = "tool_start"
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)


class SSEToolEnd(BaseModel):
    type: Literal["tool_end"] = "tool_end"
    tool_name: str
    result_preview: str
    success: bool = True


class SSEMessageEnd(BaseModel):
    type: Literal["message_end"] = "message_end"
    message_id: str
    total_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0


class SSEError(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    recoverable: bool = False


class SSEDone(BaseModel):
    type: Literal["done"] = "done"


SSEEvent = (
    SSEMessageStart
    | SSEToken
    | SSEToolStart
    | SSEToolEnd
    | SSEMessageEnd
    | SSEError
    | SSEDone
)