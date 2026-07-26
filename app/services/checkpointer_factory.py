"""Checkpointer factory — provides the LangGraph BaseCheckpointSaver.

Selectable via `LLM_CHECKPOINTER`:
- "memory"   → MemorySaver (in-process, dev/tests).
- "postgres" → AsyncPostgresSaver from langgraph-checkpoint-postgres (prod).

Single-tenant: thread_id is just str(conversation_id) (no tenant prefix).
`init()` is idempotent and called from the FastAPI lifespan; `close()` on
shutdown.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.config import settings

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

_checkpointer: "BaseCheckpointSaver | None" = None
_postgres_conn = None  # async psycopg connection we own for postgres backend


def build_thread_id(conversation_id) -> str:
    """Build the LangGraph thread_id — single-tenant: just str(conv_id)."""
    return str(conversation_id)


def build_checkpointer() -> "BaseCheckpointSaver":
    """Return the active checkpointer. Raises if postgres not initialized."""
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    if settings.llm_checkpointer == "postgres":
        raise RuntimeError(
            "Postgres checkpointer not initialized. Call checkpointer_factory.init() in lifespan."
        )

    # memory backend — lazy create
    from langgraph.checkpoint.memory import MemorySaver

    _checkpointer = MemorySaver()
    return _checkpointer


async def init() -> None:
    """Initialize the checkpointer (idempotent). Called from lifespan startup."""
    global _checkpointer, _postgres_conn

    if _checkpointer is not None:
        return

    if settings.llm_checkpointer == "postgres":
        import psycopg
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row

        _postgres_conn = await psycopg.AsyncConnection.connect(
            settings.pg_async_dsn,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        saver = AsyncPostgresSaver(conn=_postgres_conn)
        await saver.setup()
        _checkpointer = saver
        logger.info("checkpointer.postgres.ready")
    else:
        # memory backend eagerly created here so subsequent build_checkpointer()
        # returns the cached instance without importing again.
        from langgraph.checkpoint.memory import MemorySaver

        _checkpointer = MemorySaver()
        logger.info("checkpointer.memory.ready")


async def close() -> None:
    """Close the underlying postgres connection (shutdown hook)."""
    global _checkpointer, _postgres_conn
    if _postgres_conn is not None:
        await _postgres_conn.close()
        _postgres_conn = None
    _checkpointer = None
    logger.info("checkpointer.closed")


def reset() -> None:
    """Reset cached state — use in tests to isolate."""
    global _checkpointer, _postgres_conn
    _checkpointer = None
    _postgres_conn = None