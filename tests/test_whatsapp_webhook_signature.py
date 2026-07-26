"""`POST /whatsapp/webhook` MUST verify `X-Hub-Signature-256`: an HMAC-SHA256
of the raw request body keyed with the Meta app secret, compared with
`hmac.compare_digest`. Absent or invalid signatures get 403 with no
conversation created and no LLM call — `hub.verify_token` only guards the
`GET` handshake, never the POST route.

The background task (`_process_in_background`) is replaced with a no-op spy
so these tests never touch a real DB session or the Meta Graph API; only
the signature gate itself is under test.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.routers.whatsapp as whatsapp_module
from app.core.config import settings

_WEBHOOK_BODY = {
    "entry": [
        {
            "changes": [
                {
                    "value": {
                        "messages": [
                            {
                                "type": "text",
                                "from": "573000000000",
                                "id": "wamid.SIGTEST123",
                                "text": {"body": "Hola"},
                            }
                        ],
                        "contacts": [
                            {"wa_id": "573000000000", "profile": {"name": "Test"}}
                        ],
                    }
                }
            ]
        }
    ]
}
_RAW_BODY = json.dumps(_WEBHOOK_BODY).encode("utf-8")


def _sign(secret: str, raw_body: bytes = _RAW_BODY) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


@pytest.fixture
def signed_webhook_app(monkeypatch: pytest.MonkeyPatch):
    """A throwaway app mounting the real `/whatsapp/webhook` route, with a
    real (non-empty) app secret and an `app_env` that never skips
    verification, plus a spy in place of the background processor."""
    monkeypatch.setattr(settings, "whatsapp_app_secret", "test-secret")
    monkeypatch.setattr(settings, "app_env", "production")

    calls: list[tuple] = []

    async def _spy(*args, **kwargs) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(whatsapp_module, "_process_in_background", _spy)

    test_app = FastAPI()
    test_app.include_router(whatsapp_module.router)
    return test_app, calls


def test_valid_signature_is_accepted(signed_webhook_app) -> None:
    test_app, calls = signed_webhook_app
    headers = {
        "X-Hub-Signature-256": _sign("test-secret"),
        "Content-Type": "application/json",
    }
    with TestClient(test_app) as client:
        resp = client.post("/whatsapp/webhook", content=_RAW_BODY, headers=headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert len(calls) == 1


def test_invalid_signature_is_rejected(signed_webhook_app) -> None:
    test_app, calls = signed_webhook_app
    headers = {
        "X-Hub-Signature-256": _sign("wrong-secret"),
        "Content-Type": "application/json",
    }
    with TestClient(test_app) as client:
        resp = client.post("/whatsapp/webhook", content=_RAW_BODY, headers=headers)

    assert resp.status_code == 403
    assert calls == []


def test_missing_signature_is_rejected(signed_webhook_app) -> None:
    test_app, calls = signed_webhook_app
    with TestClient(test_app) as client:
        resp = client.post(
            "/whatsapp/webhook",
            content=_RAW_BODY,
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 403
    assert calls == []


def test_empty_secret_skips_verification_only_in_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local dev ergonomics: no `WHATSAPP_APP_SECRET` configured, `app_env`
    is `development` → the webhook still processes without a signature."""
    monkeypatch.setattr(settings, "whatsapp_app_secret", "")
    monkeypatch.setattr(settings, "app_env", "development")

    calls: list[tuple] = []

    async def _spy(*args, **kwargs) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(whatsapp_module, "_process_in_background", _spy)

    test_app = FastAPI()
    test_app.include_router(whatsapp_module.router)
    with TestClient(test_app) as client:
        resp = client.post(
            "/whatsapp/webhook",
            content=_RAW_BODY,
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 200
    assert len(calls) == 1


def test_empty_secret_does_not_skip_verification_outside_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty secret in a non-dev env must fail closed, not fail open."""
    monkeypatch.setattr(settings, "whatsapp_app_secret", "")
    monkeypatch.setattr(settings, "app_env", "production")

    calls: list[tuple] = []

    async def _spy(*args, **kwargs) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(whatsapp_module, "_process_in_background", _spy)

    test_app = FastAPI()
    test_app.include_router(whatsapp_module.router)
    with TestClient(test_app) as client:
        resp = client.post(
            "/whatsapp/webhook",
            content=_RAW_BODY,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _sign("anything"),
            },
        )

    assert resp.status_code == 403
    assert calls == []
