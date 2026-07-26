"""InboundMessageHandler — end-to-end processing of an inbound WhatsApp message.

Responsibilities:
1. Idempotency: skip if external_id already persisted (Meta retries on slow 200s).
2. Ensure conversation exists for this wa_id (one phone = one thread).
3. Invoke the agent synchronously (no SSE on WhatsApp).
4. Send the agent's reply back via WhatsApp Cloud API.

Kept synchronous-friendly: caller (the webhook router) responds to Meta with 200
immediately via FastAPI BackgroundTasks; this handler runs after the response.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repositories.message_repository import MessageRepository
from app.schemas.message_schema import MessageCreate
from app.services.agent_service import AgentService
from app.services.conversation_service import ConversationService
from app.services.message_service import MessageService
from app.services.whatsapp_client import get_whatsapp_client

logger = logging.getLogger(__name__)


class InboundMessageHandler:
    """One inbound message → agent turn → outbound reply."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.conversation_service = ConversationService(session)
        self.message_service = MessageService(session)
        self.message_repo = MessageRepository(session)

    async def handle(
        self,
        *,
        wa_id: str,
        text: str,
        external_id: str,
        profile_name: str | None = None,
        dry_run: bool = False,
    ) -> None:
        """Process an inbound WhatsApp text message.

        Idempotent on `external_id` — safe to call multiple times for the same
        Meta delivery. Logs outcomes; never raises (background task).

        When `dry_run=True`, skips the outbound call to the Meta Graph API and
        only logs the agent's reply. Used by the dev simulator endpoint so
        iterating on the agent does not burn WhatsApp quota.
        """
        # Idempotency: if we've already seen this message id, stop.
        existing = await self.message_repo.find_by_external_id(external_id)
        if existing is not None:
            logger.info("inbound.duplicate", extra={"external_id": external_id})
            return

        # Ensure conversation for this phone number.
        title = f"WhatsApp - {profile_name}" if profile_name else "WhatsApp"
        conv = await self.conversation_service.get_or_create_by_wa_id(wa_id, title=title)

        # Run the agent synchronously (uses OpenAI + tools + checkpointer).
        try:
            agent = AgentService(self.session)
            payload = MessageCreate(content=text)
            result = await agent.send_message(conv.id, payload, external_id=external_id)
        except Exception as exc:
            logger.exception("inbound.agent_failed", extra={"conversation_id": str(conv.id)})
            reply = "Disculpá, tuve un problema para procesar tu mensaje. Intentá nuevamente."
            if not dry_run:
                await get_whatsapp_client().send_text(wa_id, reply)
            else:
                logger.info("inbound.dry_run.error_reply", extra={"wa_id": wa_id, "reply": reply})
            return

        assistant_msg = result.get("assistant_message")
        reply = assistant_msg.content if assistant_msg else None
        if not reply:
            reply = "Disculpa, no entendí. ¿Me lo puedes repetir?"

        if not dry_run:
            await get_whatsapp_client().send_text(wa_id, reply)
        else:
            logger.info("inbound.dry_run.reply", extra={"wa_id": wa_id, "reply": reply})

        logger.info("inbound.complete", extra={
            "conversation_id": str(conv.id), "wa_id": wa_id, "reply_len": len(reply),
            "dry_run": dry_run,
        })