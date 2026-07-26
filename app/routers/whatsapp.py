"""WhatsApp webhook router — Meta Cloud API integration.

GET  /whatsapp/webhook → initial verification handshake (hub.verify_token).
POST /whatsapp/webhook → inbound messages + statuses from Meta.

No auth: this endpoint is itself the auth boundary for Meta callbacks.
`hub.verify_token` guards the GET handshake only — it does NOT cover the
POST route. POST requests are authenticated via the `X-Hub-Signature-256`
header: an HMAC-SHA256 of the raw request body keyed with the Meta app
secret (`WHATSAPP_APP_SECRET`).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Query, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse

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
    or None if no inbound message is present (it's a status, not a message)."""
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
                text_body = _inbound_text(msg)
                if text_body is None:
                    continue
                wa_id = msg.get("from")
                external_id = msg.get("id")
                profile_name = None
                for c in contacts:
                    if c.get("wa_id") == wa_id:
                        profile_name = (c.get("profile") or {}).get("name")
                if wa_id and external_id:
                    return wa_id, text_body, external_id, profile_name
    return None


def _inbound_text(msg: dict) -> str | None:
    """The pipeline-facing text for one inbound message, or `None` to skip it.

    Two shapes are handled:
    - `type == "text"` — the free-form `text.body`, as before.
    - `type == "interactive"` — a quick-reply button or list-row tap. Meta
      puts the tapped option's `id` under `button_reply` or `list_reply`; that
      id was set to the field's canonical slug when the message was rendered
      (`app.services.whatsapp_interactive.render_options`), so handing it to
      the pipeline exactly where `text.body` goes today reaches the existing
      deterministic parser with zero extra interpretation — `domain_normalizer
      .normalize` already accepts a canonical slug as well as the verbatim
      label (see its `_build_lookup` docstring).

    Previously any `type != "text"` message (including every tactile tap) was
    silently dropped here — not even acknowledged — which meant no button or
    list reply worked at all.

    Any other message type (image, audio, a delivery status, …) is not
    handled this iteration and returns `None`.
    """
    msg_type = msg.get("type")
    if msg_type == "text":
        return (msg.get("text", {}) or {}).get("body", "")
    if msg_type == "interactive":
        interactive = msg.get("interactive") or {}
        button_reply = interactive.get("button_reply") or {}
        if button_reply.get("id"):
            return button_reply["id"]
        list_reply = interactive.get("list_reply") or {}
        if list_reply.get("id"):
            return list_reply["id"]
        return None
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


def _skip_signature_verification() -> bool:
    """Whether an empty `WHATSAPP_APP_SECRET` should skip verification.

    Only true in `development` — local iteration should not require a real
    Meta app secret. In any other `app_env`, an empty secret does NOT skip
    verification: the HMAC comparison below will simply never match a real
    Meta-signed request, so the endpoint fails closed (403) instead of
    silently accepting unsigned payloads.
    """
    if settings.whatsapp_app_secret:
        return False
    if settings.app_env == "development":
        logger.warning(
            "whatsapp.webhook.signature_verification_skipped: "
            "WHATSAPP_APP_SECRET is empty — skipping signature verification "
            "(development only)."
        )
        return True
    return False


def _signature_is_valid(raw_body: bytes, signature_header: str | None) -> bool:
    """HMAC-SHA256 of the raw body, keyed with the app secret, compared with
    `hmac.compare_digest` against `X-Hub-Signature-256: sha256=<hex>`."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.whatsapp_app_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    provided = signature_header[len("sha256="):]
    return hmac.compare_digest(expected, provided)


@router.post("/webhook", response_model=None)
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict | JSONResponse:
    """Receive Meta webhook POST. Return 200 fast; process in background.

    Reads the raw body once (the signature is computed over the raw bytes,
    not a re-serialized JSON payload) and reuses it both for signature
    verification and for parsing.
    """
    raw_body = await request.body()

    if not _skip_signature_verification():
        signature_header = request.headers.get("X-Hub-Signature-256")
        if not _signature_is_valid(raw_body, signature_header):
            logger.warning("whatsapp.webhook.signature_invalid")
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN, content={"status": "forbidden"}
            )

    try:
        body = json.loads(raw_body)
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


def _register_simulate_route() -> None:
    """Register `POST /whatsapp/simulate` only in `development`.

    With `dry_run=false` this endpoint is an open relay: it sends arbitrary
    WhatsApp messages to arbitrary recipients using the project's Meta
    credentials. Registering it unconditionally would make any non-dev
    deployment (e.g. the public Fly.io demo URL) an open relay. In any other
    `app_env` the route is simply never added to the router, so FastAPI
    answers 404 rather than 200/403 — there is nothing to authenticate
    against because the route does not exist.
    """
    if settings.app_env != "development":
        logger.info(
            "whatsapp.simulate.not_registered", extra={"app_env": settings.app_env}
        )
        return

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

        Only registered when `settings.app_env == "development"` — see the
        `Public Deployment Hardening` requirement in the `demo-deployment` spec.
        """
        ext_id = external_id or f"sim_{uuid.uuid4().hex}"
        profile = "Dev Simulator"
        logger.info("whatsapp.simulate", extra={"from": from_phone, "external_id": ext_id, "dry_run": dry_run})
        background_tasks.add_task(_process_in_background, from_phone, text, ext_id, profile, dry_run)
        return {"status": "queued", "from": from_phone, "external_id": ext_id, "dry_run": dry_run}


_register_simulate_route()