"""`type == "interactive"` webhook payloads must not be silently dropped.

Before this change, `_extract_inbound` only handled `msg["type"] == "text"`,
so a quick-reply button tap or a list-row tap arrived as `type: "interactive"`
and was skipped entirely — not even acknowledged, and nothing downstream ever
saw the tap. This asserts the fix: `button_reply.id` and `list_reply.id` are
both fed into the pipeline exactly where `text.body` goes today.
"""

from __future__ import annotations

from app.routers.whatsapp import _extract_inbound


def _webhook(message: dict) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [message],
                            "contacts": [
                                {"wa_id": "573000000000", "profile": {"name": "Test"}}
                            ],
                        }
                    }
                ]
            }
        ]
    }


def test_text_message_still_extracts_body() -> None:
    body = _webhook(
        {
            "type": "text",
            "from": "573000000000",
            "id": "wamid.TEXT1",
            "text": {"body": "Hola"},
        }
    )
    assert _extract_inbound(body) == ("573000000000", "Hola", "wamid.TEXT1", "Test")


def test_button_reply_id_is_extracted() -> None:
    body = _webhook(
        {
            "type": "interactive",
            "from": "573000000000",
            "id": "wamid.BTN1",
            "interactive": {
                "type": "button_reply",
                "button_reply": {"id": "termino_fijo", "title": "Termino fijo"},
            },
        }
    )
    assert _extract_inbound(body) == (
        "573000000000",
        "termino_fijo",
        "wamid.BTN1",
        "Test",
    )


def test_list_reply_id_is_extracted() -> None:
    body = _webhook(
        {
            "type": "interactive",
            "from": "573000000000",
            "id": "wamid.LIST1",
            "interactive": {
                "type": "list_reply",
                "list_reply": {"id": "4_8m", "title": "4 a 8 millones"},
            },
        }
    )
    assert _extract_inbound(body) == ("573000000000", "4_8m", "wamid.LIST1", "Test")


def test_interactive_message_with_no_reply_payload_is_skipped() -> None:
    """An interactive webhook Meta considers malformed — no reply id at
    all — must not crash the extractor; it is simply not an inbound message."""
    body = _webhook(
        {
            "type": "interactive",
            "from": "573000000000",
            "id": "wamid.EMPTY1",
            "interactive": {"type": "button_reply", "button_reply": {}},
        }
    )
    assert _extract_inbound(body) is None
