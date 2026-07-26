"""WhatsApp webhook router — Meta Cloud API integration.

GET  /whatsapp/webhook → initial verification handshake (hub.verify_token).
POST /whatsapp/webhook → inbound messages + statuses from Meta.

No auth: this endpoint is itself the auth boundary for Meta callbacks.
Verify-token guards the GET; signature verification is a TODO (Meta signs the
X-Hub-Signature-256 header). For hackathon, token check suffices.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Query, Request, status
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.core.db import async_session_maker
from app.services.inbound_handler import InboundMessageHandler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


@router.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
) -> PlainTextResponse:
    """Meta's one-time webhook verification: echo challenge if token matches."""
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_webhook_verify_token:
        logger.info("whatsapp.verify.ok")
        return PlainTextResponse(content=hub_challenge, status_code=status.HTTP_200_OK)
    logger.warning("whatsapp.verify.failed", extra={"hub_mode": hub_mode})
    return PlainTextResponse(content="forbidden", status_code=status.HTTP_403_FORBIDDEN)


def _extract_inbound(body: dict) -> tuple[str, str, str, str | None] | None:
    """Pull (wa_id, text, external_id, profile_name) from a Meta webhook body,
    or None if no inbound text message present (it's a status, not a message)."""
    if not body or "entry" not in body:
        return None
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            contacts = value.get("contacts", [])
            if not messages:
                continue
            for msg in messages:
                if msg.get("type") != "text":
                    continue  # only text for this iteration
                wa_id = msg.get("from")
                external_id = msg.get("id")
                text_body = (msg.get("text", {}) or {}).get("body", "")
                profile_name = None
                for c in contacts:
                    if c.get("wa_id") == wa_id:
                        profile_name = (c.get("profile") or {}).get("name")
                if wa_id and external_id:
                    return wa_id, text_body, external_id, profile_name
    return None


async def _process_in_background(
    wa_id: str, text: str, external_id: str, profile_name: str | None, dry_run: bool = False
) -> None:
    """Own its own DB session since it runs after the HTTP response is sent."""
    async with async_session_maker() as session:
        try:
            handler = InboundMessageHandler(session)
            await handler.handle(
                wa_id=wa_id, text=text, external_id=external_id,
                profile_name=profile_name, dry_run=dry_run,
            )
        except Exception:
            logger.exception("whatsapp.background.process_failed", extra={"external_id": external_id})


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """Receive Meta webhook POST. Return 200 fast; process in background."""
    try:
        body = await request.json()
    except Exception:
        # If not JSON, ignore. Meta occasionally sends other formats.
        logger.warning("whatsapp.post.non_json_body")
        return {"status": "ignored"}

    extracted = _extract_inbound(body)
    if extracted is None:
        # Not an inbound text message (probably a status update). Acknowledge.
        return {"status": "acknowledged"}

    wa_id, text, external_id, profile_name = extracted
    background_tasks.add_task(_process_in_background, wa_id, text, external_id, profile_name)
    return {"status": "queued"}


@router.post("/simulate")
async def simulate_inbound(
    background_tasks: BackgroundTasks,
    text: str = Query(..., min_length=1, max_length=4000, description="Message text as the client would write it."),
    from_phone: str = Query(..., min_length=8, max_length=20, alias="from", description="Phone number in international format, digits only (e.g. 584245032990). Acts as the conversation key."),
    dry_run: bool = Query(True, description="When true, runs the agent but skips the outbound message to Meta (dev iteration without burning quota). Set to false to receive the reply on the real WhatsApp."),
    external_id: str | None = Query(None, description="Optional idempotency id. Auto-generated if omitted so retries don't replay the agent."),
) -> dict:
    """Dev-only simulator of an inbound WhatsApp message.

    Behaves identically to the real Meta webhook POST: enqueues background
    processing, runs the agent, and (unless `dry_run=true`) sends the reply
    through the Meta Graph API to `from`. Use this from Swagger/Postman to
    test the conversation flow without needing an actual inbound message.
    """
    ext_id = external_id or f"sim_{uuid.uuid4().hex}"
    profile = "Dev Simulator"
    logger.info("whatsapp.simulate", extra={"from": from_phone, "external_id": ext_id, "dry_run": dry_run})
    background_tasks.add_task(_process_in_background, from_phone, text, ext_id, profile, dry_run)
    return {"status": "queued", "from": from_phone, "external_id": ext_id, "dry_run": dry_run}