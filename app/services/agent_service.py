"""AgentService — lean orchestrator for the Vivi conversational agent.

Decomposed from the reference god class into collaborators:
- ConversationService / MessageService own persistence.
- llm_factory / checkpointer_factory / graph.builder own graph wiring.
- tool_context owns runtime DI.

Orchestrates only: validate → persist → restore state → build graph input →
invoke/stream → persist → (SSE mapping on stream). No safety, no HITL, no
auto-titling. Kept under ~250 lines.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.graph.builder import DEFAULT_ROLE, build_graph
from app.prompts.system import wrap_user_input
from app.schemas.chat_schema import (SSEDone, SSEError, SSEMessageEnd, SSEMessageStart,
                                       SSEToken, SSEToolEnd, SSEToolStart)
from app.schemas.message_schema import MessageCreate
from app.services.checkpointer_factory import build_thread_id
from app.services.conversation_service import ConversationService
from app.services.llm_factory import is_llm_configured
from app.services.lead_state_rebuilder import rebuild_lead_profile
from app.services.message_service import MessageService
from app.services.tool_context import ToolContext

logger = logging.getLogger(__name__)


class AgentService:
    """Lean orchestrator for the agent graph."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.conversation_service = ConversationService(session)
        self.message_service = MessageService(session)

    # ── Synchronous turn ──────────────────────────────────────────────

    async def send_message(
        self,
        conversation_id: uuid.UUID,
        payload: MessageCreate,
    ) -> dict:
        """Validate, persist user msg, invoke graph, persist assistant turn."""
        content = (payload.content or "").strip()
        if not content:
            raise ValidationError("El mensaje no puede estar vacío.")
        if not is_llm_configured():
            raise ServiceUnavailableError(
                message="AI agent is not configured.", error_code="openai_not_configured"
            )

        conv = await self.conversation_service.get_or_404(conversation_id)

        await self.message_service.persist_user_message(conv.id, content)

        thread_id = build_thread_id(conv.id)
        tool_context = ToolContext(session=self.session, conversation_id=conv.id)
        config = self._build_run_config(thread_id, tool_context)
        graph = build_graph(DEFAULT_ROLE)

        checkpointed = await self._checkpointed_state(graph, config)
        graph_input = await self._build_graph_input(conv.id, content, checkpointed)
        already_seen = len(checkpointed.get("messages") or [])

        try:
            result = await asyncio.wait_for(
                graph.ainvoke(graph_input, config=config),
                timeout=settings.agent_timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise ServiceUnavailableError(
                message=f"El agente no respondió en {settings.agent_timeout_seconds}s.",
            )

        return await self._persist_turn(conv.id, result, already_seen)

    # ── Streaming turn (SSE) ──────────────────────────────────────────

    async def stream_message(
        self,
        conversation_id: uuid.UUID,
        payload: MessageCreate,
    ) -> AsyncGenerator[dict, None]:
        """Stream the agent turn as SSE event dicts."""
        content = (payload.content or "").strip()

        async def _err(code: str, message: str, recoverable: bool = False):
            yield self._sse("error", SSEError(type="error", code=code, message=message, recoverable=recoverable))
            yield self._sse("done", SSEDone(type="done"))

        if not content:
            async for e in _err("validation_error", "El mensaje no puede estar vacío.", True):
                yield e
            return
        if not is_llm_configured():
            async for e in _err("service_unavailable", "AI agent is not configured."):
                yield e
            return

        try:
            conv = await self.conversation_service.get_or_404(conversation_id)
        except Exception as exc:
            async for e in _err("not_found", str(exc)):
                yield e
            return

        await self.message_service.persist_user_message(conv.id, content)
        thread_id = build_thread_id(conv.id)
        tool_context = ToolContext(session=self.session, conversation_id=conv.id)
        config = self._build_run_config(thread_id, tool_context)
        graph = build_graph(DEFAULT_ROLE)
        checkpointed = await self._checkpointed_state(graph, config)
        graph_input = await self._build_graph_input(conv.id, content, checkpointed)

        assistant_id = str(uuid.uuid4())
        yield self._sse("message_start", SSEMessageStart(
            type="message_start", message_id=assistant_id, conversation_id=str(conv.id)
        ))

        chunks: list[str] = []
        tokens_prompt = 0
        tokens_completion = 0
        tools_emitted: set[str] = set()

        try:
            stream = graph.astream_events(graph_input, config=config, version="v2")
            async for event in stream:
                kind = event.get("event")
                name = event.get("name", "")
                data = event.get("data", {})

                if kind == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    if chunk and hasattr(chunk, "content"):
                        token = chunk.content or ""
                        if token:
                            chunks.append(token)
                            yield self._sse("token", SSEToken(type="token", delta=token))
                elif kind == "on_tool_start":
                    if name and name not in tools_emitted:
                        tools_emitted.add(name)
                        yield self._sse("tool_start", SSEToolStart(type="tool_start", tool_name=name, args=data.get("input", {})))
                elif kind == "on_tool_end":
                    yield self._sse("tool_end", SSEToolEnd(type="tool_end", tool_name=name or "tool", result_preview=str(data.get("output"))[:120]))
                elif kind == "on_chat_model_end":
                    out_msg = data.get("output")
                    if out_msg:
                        usage = getattr(out_msg, "usage_metadata", None) or {}
                        if usage and isinstance(usage, dict):
                            tokens_prompt += usage.get("input_tokens", 0) or 0
                            tokens_completion += usage.get("output_tokens", 0) or 0

        except asyncio.TimeoutError:
            yield self._sse("error", SSEError(type="error", code="timeout",
                        message=f"El agente no respondió en {settings.agent_timeout_seconds}s.", recoverable=True))
        except Exception as exc:
            logger.exception("agent_stream_error")
            yield self._sse("error", SSEError(type="error", code="internal_error",
                        message=f"Error del agente: {exc}", recoverable=False))
        finally:
            full = "".join(chunks) or "(No pude generar una respuesta en este momento. ¿Puedes intentarlo de nuevo?)"
            entity = await self.message_service.persist_assistant_message(
                conv.id, full, tokens_prompt=tokens_prompt, tokens_completion=tokens_completion,
            )
            await self.conversation_service.increment_message_counter(
                conv.id, tokens_added=tokens_prompt + tokens_completion
            )
            logger.info("agent_stream_complete", extra={"conversation_id": str(conv.id),
                         "tokens_prompt": tokens_prompt, "tokens_completion": tokens_completion,
                         "tools_used": list(tools_emitted)})
            yield self._sse("message_end", SSEMessageEnd(type="message_end", message_id=str(entity.id),
                                                          total_tokens=tokens_prompt + tokens_completion,
                                                          total_prompt_tokens=tokens_prompt,
                                                          total_completion_tokens=tokens_completion))
            yield self._sse("done", SSEDone(type="done"))

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    async def _checkpointed_state(graph, config: dict) -> dict:
        """The thread's persisted state, or `{}` when the checkpointer lost it."""
        try:
            snapshot = await graph.aget_state(config)
        except Exception:  # noqa: BLE001 — a missing thread is not an error here
            logger.debug("agent.no_checkpoint")
            return {}
        return dict(getattr(snapshot, "values", None) or {})

    async def _build_graph_input(
        self, conv_id: uuid.UUID, new_user_content: str, checkpointed: dict
    ) -> dict:
        """One turn of input: the raw reply plus the wrapped user message.

        The per-node system prompt is rendered inside each node, so no monolithic
        `SystemMessage` is injected here. Conversation history comes from the
        checkpointer rather than from the `messages` table — replaying the table
        every turn would duplicate it into the accumulating `add_messages`
        channel.
        """
        graph_input: dict[str, Any] = {
            "pending_user_reply": new_user_content,
            "messages": [HumanMessage(content=wrap_user_input(new_user_content))],
        }
        if checkpointed.get("lead_profile"):
            return graph_input

        # Crash recovery: the checkpointer lost the thread but the `leads` row
        # survived, so the lead is not asked everything a second time.
        restored = await rebuild_lead_profile(self.session, conv_id)
        if restored:
            graph_input["lead_profile"] = restored
        return graph_input

    @staticmethod
    def _build_run_config(thread_id: str, tool_context: ToolContext) -> dict:
        return {
            "configurable": {"thread_id": thread_id, "tool_context": tool_context},
            "recursion_limit": settings.agent_max_turns * 3,
        }

    async def _persist_turn(self, conv_id, graph_result, already_seen: int = 0) -> dict:
        """Persist the assistant + tool messages this turn produced.

        `already_seen` is the message count the checkpointer held before the
        invocation. The graph's `messages` channel accumulates across the whole
        conversation, so persisting the full list every turn would rewrite every
        earlier assistant reply into the `messages` table.
        """
        from app.schemas.message_schema import MessageResponse

        assistant_msg = None
        tool_messages: list = []
        total_tokens = 0
        produced = list(graph_result.get("messages", []))[already_seen:]
        for msg in produced:
            if not isinstance(msg, (AIMessage, ToolMessage)):
                continue
            entity = self.message_service.lc_message_to_entity(msg, conv_id)
            if entity is None:
                continue
            self.session.add(entity)
            await self.session.flush()
            await self.session.refresh(entity)
            total_tokens += entity.tokens_prompt + entity.tokens_completion
            resp = MessageResponse.model_validate(entity)
            if entity.role == "assistant":
                assistant_msg = resp
            elif entity.role == "tool":
                tool_messages.append(resp)
        await self.session.commit()
        await self.conversation_service.increment_message_counter(conv_id, tokens_added=total_tokens)
        if assistant_msg is None:
            fb = await self.message_service.persist_assistant_message(
                conv_id, "(No pude generar una respuesta en este momento. ¿Puedes intentarlo de nuevo?)"
            )
            assistant_msg = MessageResponse.model_validate(fb)
        return {"user_message": None, "assistant_message": assistant_msg, "tool_messages": tool_messages}

    async def _maybe_persist_tool_messages(self, conv_id, graph_input, config) -> None:
        """Best-effort tool message persistence — skipped in stream mode this iteration."""
        # TODO: HITL via LangGraph interrupts in next iteration — revisit
        # full tool message persistence once we capture final graph state.
        return

    @staticmethod
    def _sse(event_name: str, payload) -> dict:
        return {"event": event_name, "data": json.dumps(payload.model_dump(mode="json"))}