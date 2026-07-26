"""Shared tool helpers: `@safe_tool`, `serialize_result`, `json_dumps`.

`safe_tool` catches exceptions and returns a JSON error string the LLM can
react to, instead of crashing the graph. `serialize_result` truncates large
outputs to `AGENT_MAX_TOOL_RESULT_CHARS` to avoid flooding the LLM context.
"""

from __future__ import annotations

import functools
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID

from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)


def _default_json(obj: Any) -> Any:
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    return str(obj)


def json_dumps(data: Any, indent: int | None = None) -> str:
    """JSON dump supporting UUID/Decimal/datetime and Pydantic models."""
    return json.dumps(data, default=_default_json, ensure_ascii=False, indent=indent)


def _to_plain(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, list):
        return [_to_plain(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    return obj


def serialize_result(result: Any, max_chars: int | None = None) -> str:
    """Normalize a tool response to a compact, size-capped JSON string."""
    plain = _to_plain(result)
    max_chars = max_chars or settings.agent_max_tool_result_chars
    dumped = json_dumps(plain)

    if len(dumped) <= max_chars:
        return dumped

    truncated = dumped[: max_chars - 200]
    last = max(truncated.rfind(","), truncated.rfind("}"), truncated.rfind("]"))
    if last > 0:
        truncated = truncated[: last + 1]
    return (
        truncated
        + '..."_truncated": true, "_hint": "Resultado recortado por límite de tamaño. '
        'Acotá la consulta con filtros más específicos."}'
    )


def safe_tool(fn: Callable) -> Callable:
    """Decorator for async tools: catch exceptions, return JSON error string.

    Lets the LLM react to a tool failure (retry / explain) instead of raising
    and breaking the graph.
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        tool_name = fn.__name__
        try:
            result = await fn(*args, **kwargs)
            if isinstance(result, str):
                return result
            return serialize_result(result)
        except Exception as e:
            logger.exception("tool_unexpected_error", extra={"tool_name": tool_name})
            return json_dumps(
                {
                    "error": True,
                    "code": "internal_tool_error",
                    "message": f"La tool {tool_name} falló inesperadamente: {type(e).__name__}: {e}",
                }
            )

    return wrapper