"""MessageService — message persistence + history loading.

Lean collaborator extracted from the reference god class. Owns persisting
new messages (user/assistant/tool) and loading recent history for the graph.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.message_model import MessageEntity
from app.models.repositories.message_repository import MessageRepository
from app.prompts.system import wrap_user_input

logger = logging.getLogger(__name__)


class MessageService:
    """Persistence collaborator for messages."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = MessageRepository(session)

    async def persist_user_message(
        self,
        conversation_id: uuid.UUID,
        content: str,
        *,
        external_id: str | None = None,
    ) -> MessageEntity:
        entity = MessageEntity(
            conversation_id=conversation_id,
            role="user",
            content=content,
            external_id=external_id,
        )
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        await self.session.commit()
        return entity

    async def persist_assistant_message(
        self,
        conversation_id: uuid.UUID,
        content: str,
        *,
        tokens_prompt: int = 0,
        tokens_completion: int = 0,
        tool_calls: dict | None = None,
        metadata: dict | None = None,
    ) -> MessageEntity:
        entity = MessageEntity(
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            tool_calls=tool_calls,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            message_metadata=metadata,
        )
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        await self.session.commit()
        return entity

    async def persist_tool_message(
        self,
        conversation_id: uuid.UUID,
        *,
        content: str,
        tool_call_id: str,
        tool_name: str | None,
    ) -> MessageEntity:
        entity = MessageEntity(
            conversation_id=conversation_id,
            role="tool",
            content=content,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        await self.session.commit()
        return entity

    async def load_history(self, conversation_id: uuid.UUID) -> list[MessageEntity]:
        """Load the last N messages in chronological order (oldest first)."""
        return await self.repo.recent_history(
            conversation_id, limit=settings.agent_history_limit
        )

    def to_lc_message(self, entity: MessageEntity):
        """Convert a persisted MessageEntity into a LangChain message."""
        if entity.role == "user":
            return HumanMessage(content=wrap_user_input(entity.content or ""))
        if entity.role == "assistant":
            return AIMessage(content=entity.content or "")
        if entity.role == "tool":
            return ToolMessage(
                content=entity.content or "",
                tool_call_id=entity.tool_call_id or "unknown",
                name=entity.tool_name,
            )
        return SystemMessage(content=entity.content or "")

    def lc_message_to_entity(self, msg: Any, conversation_id: uuid.UUID) -> MessageEntity | None:
        """Convert an LLM message to a persistable entity (assistant/tool only).

        Returns None for HumanMessage/SystemMessage (user persisted separately,
        system prompt is never persisted).
        """
        if isinstance(msg, AIMessage):
            tokens_prompt = 0
            tokens_completion = 0
            metadata: dict | None = None
            usage = getattr(msg, "usage_metadata", None) or {}
            if usage:
                tokens_prompt = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
                tokens_completion = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
                metadata = {"token_usage": dict(usage)}
            tool_calls = None
            if msg.tool_calls:
                tool_calls = {
                    "calls": [
                        {"id": tc.get("id"), "name": tc.get("name"), "args": tc.get("args", {})}
                        for tc in msg.tool_calls
                    ]
                }
            return MessageEntity(
                conversation_id=conversation_id,
                role="assistant",
                content=msg.content if isinstance(msg.content, str) else None,
                tool_calls=tool_calls,
                tokens_prompt=tokens_prompt,
                tokens_completion=tokens_completion,
                message_metadata=metadata,
            )
        if isinstance(msg, ToolMessage):
            return MessageEntity(
                conversation_id=conversation_id,
                role="tool",
                content=msg.content if isinstance(msg.content, str) else str(msg.content),
                tool_call_id=msg.tool_call_id or "unknown",
                tool_name=getattr(msg, "name", None),
            )
        return None