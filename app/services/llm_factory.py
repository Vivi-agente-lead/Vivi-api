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

    # The model has exactly one job here: rewording a question that already
    # exists, in one or two sentences (`app/graph/nodes/_common.py::phrase`).
    # Every parameter below is sized for that, because this call sits between
    # the person's answer and Vivi's next message — it is the whole perceived
    # latency of the conversation.
    #
    # `max_tokens` bounds generation, which is what actually costs time; without
    # it a chatty completion stretches a two-line question into seconds. The
    # timeout is short and separate from `agent_timeout_seconds` (which covers
    # the whole graph): a rewrite that has not arrived in a few seconds is worth
    # less than answering promptly, and `phrase` already falls back to the
    # deterministic question. One retry rather than two for the same reason —
    # retrying a timeout is how a slow turn becomes a very slow turn.
    return ChatOpenAI(
        model=settings.openai_model,
        temperature=settings.openai_temperature,
        api_key=settings.openai_api_key,
        max_retries=1,
        timeout=settings.llm_phrase_timeout_seconds,
        max_tokens=settings.llm_phrase_max_tokens,
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