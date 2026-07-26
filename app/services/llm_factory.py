"""LLM factory — builds and caches the OpenAI ChatOpenAI client.

Centralized so graph, tests and health checks share one client/one config.
If OPENAI_API_KEY is empty (dev), `is_llm_configured()` returns False and the
agent endpoints report 503 instead of crashing.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from app.core.config import settings
from app.core.exceptions import ServiceUnavailableError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI


def is_llm_configured() -> bool:
    """True if an OpenAI API key is configured."""
    return bool(settings.openai_api_key)


@lru_cache(maxsize=1)
def _build_llm_cached() -> "ChatOpenAI":
    """Build and cache the ChatOpenAI singleton."""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.openai_model,
        temperature=settings.openai_temperature,
        api_key=settings.openai_api_key,
        max_retries=2,
        timeout=settings.agent_timeout_seconds,
    )


def build_llm() -> "ChatOpenAI":
    """Return the configured LLM, or raise 503 if not configured."""
    if not is_llm_configured():
        raise ServiceUnavailableError(
            message="OpenAI LLM is not configured (OPENAI_API_KEY empty).",
            error_code="openai_not_configured",
        )
    return _build_llm_cached()


def reset_llm_cache() -> None:
    """Invalidate the singleton — use in tests or when rotating credentials."""
    _build_llm_cached.cache_clear()