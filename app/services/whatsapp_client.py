"""WhatsAppClient — thin async client to send outbound messages via Meta Graph API."""

from __future__ import annotations

import logging
from typing import Any, Sequence

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class WhatsAppClient:
    """Posts outbound text messages to the Meta Graph API.

    Stateless — uses the shared token/phone-number-id from settings.
    Designed for background-task use after the agent produces a reply.
    """

    BASE_URL = "https://graph.facebook.com"

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout

    @property
    def _url(self) -> str:
        return f"{self.BASE_URL}/{settings.whatsapp_api_version}/{settings.whatsapp_phone_number_id}/messages"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.whatsapp_api_token}",
            "Content-Type": "application/json",
        }

    async def send_text(self, to: str, body: str) -> dict[str, Any]:
        """Send a free-form text message. Requires the 24h customer-service window."""
        if not settings.whatsapp_api_token:
            logger.warning("whatsapp.send_text.skipped", extra={"reason": "no_token", "to": to})
            return {"status": "skipped", "reason": "WHATSAPP_API_TOKEN not configured"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        }
        return await self._post(to, payload, label="send_text")

    async def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str = "en_US",
    ) -> dict[str, Any]:
        """Send an approved template to open a conversation session.

        Templates must be pre-approved in the Meta WhatsApp Manager. Use this
        to initiate outbound — the customer has not yet written you, and free
        form text is not allowed outside the 24h customer-service window.
        When the recipient replies, the inbound webhook creates the conversation.
        """
        if not settings.whatsapp_api_token:
            logger.warning("whatsapp.send_template.skipped", extra={"reason": "no_token", "to": to})
            return {"status": "skipped", "reason": "WHATSAPP_API_TOKEN not configured"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            },
        }
        return await self._post(to, payload, label="send_template")

    async def send_interactive_buttons(
        self, to: str, body: str, buttons: Sequence[dict[str, Any]]
    ) -> dict[str, Any]:
        """Send a quick-reply `interactive.type == "button"` message.

        Meta caps this at 3 buttons; `buttons` is expected to already respect
        that (see `app.services.whatsapp_interactive.render_options`) — this
        method does not re-validate the shape, only posts it.
        """
        if not settings.whatsapp_api_token:
            logger.warning("whatsapp.send_interactive_buttons.skipped", extra={"reason": "no_token", "to": to})
            return {"status": "skipped", "reason": "WHATSAPP_API_TOKEN not configured"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {"buttons": list(buttons)},
            },
        }
        return await self._post(to, payload, label="send_interactive_buttons")

    async def send_interactive_list(
        self,
        to: str,
        body: str,
        sections: Sequence[dict[str, Any]],
        *,
        button_text: str = "Ver opciones",
    ) -> dict[str, Any]:
        """Send an `interactive.type == "list"` message (up to 10x10 rows).

        `sections` is expected to already respect Meta's caps (see
        `app.services.whatsapp_interactive.render_options`) — this method does
        not re-validate the shape, only posts it.
        """
        if not settings.whatsapp_api_token:
            logger.warning("whatsapp.send_interactive_list.skipped", extra={"reason": "no_token", "to": to})
            return {"status": "skipped", "reason": "WHATSAPP_API_TOKEN not configured"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body},
                "action": {"button": button_text, "sections": list(sections)},
            },
        }
        return await self._post(to, payload, label="send_interactive_list")

    async def _post(self, to: str, payload: dict[str, Any], *, label: str) -> dict[str, Any]:
        """Shared HTTP POST to the Graph API messages endpoint."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._url, json=payload, headers=self._headers)
            if resp.status_code >= 400:
                logger.error(
                    f"whatsapp.{label}.error",
                    extra={"to": to, "status": resp.status_code, "body": resp.text[:500]},
                )
                return {"status": "error", "code": resp.status_code, "detail": resp.text}
            return {"status": "ok", "data": resp.json()}
        except Exception as exc:
            logger.exception(f"whatsapp.{label}.exception", extra={"to": to})
            return {"status": "exception", "detail": str(exc)}


_client_singleton: WhatsAppClient | None = None


def get_whatsapp_client() -> WhatsAppClient:
    """Return a process-wide WhatsAppClient singleton (stateless; safe to share)."""
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = WhatsAppClient()
    return _client_singleton