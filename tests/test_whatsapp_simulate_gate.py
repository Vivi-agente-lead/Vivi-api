"""`POST /whatsapp/simulate` must only exist when `settings.app_env ==
"development"`. In any other environment the route is not registered at all,
so FastAPI answers 404 — with `dry_run=false` on a public URL this endpoint
is an open relay able to send arbitrary WhatsApp messages through the
project's Meta credentials.

The router module decides registration at import time, so each test reloads
`app.routers.whatsapp` under a monkeypatched `settings.app_env` and mounts
the freshly built router onto a throwaway `FastAPI` app — the real
`app.main.app` (already built at process import time) is left untouched.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings


@pytest.fixture
def whatsapp_module_reloader(monkeypatch: pytest.MonkeyPatch):
    """Yields a builder: `app_env -> FastAPI app mounting a freshly reloaded
    `app.routers.whatsapp` router. Restores the module to its normal
    (development) state on teardown."""
    import app.routers.whatsapp as whatsapp_module

    def build(app_env: str) -> FastAPI:
        monkeypatch.setattr(settings, "app_env", app_env)
        importlib.reload(whatsapp_module)
        # Route registration is the only thing under test — never let the
        # background task touch a real DB/Meta call.
        monkeypatch.setattr(whatsapp_module, "_process_in_background", _noop_background)
        test_app = FastAPI()
        test_app.include_router(whatsapp_module.router)
        return test_app

    yield build

    # Reload back to whatever env is active once monkeypatch has reverted,
    # so later tests importing the real module see normal behavior.
    importlib.reload(whatsapp_module)


async def _noop_background(*args, **kwargs) -> None:
    return None


def test_simulate_is_registered_in_development(whatsapp_module_reloader) -> None:
    test_app = whatsapp_module_reloader("development")
    with TestClient(test_app) as client:
        resp = client.post(
            "/whatsapp/simulate", params={"text": "Hola", "from": "584245032990"}
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


@pytest.mark.parametrize("app_env", ["production", "staging", "test"])
def test_simulate_is_not_registered_outside_development(
    whatsapp_module_reloader, app_env: str
) -> None:
    test_app = whatsapp_module_reloader(app_env)
    with TestClient(test_app) as client:
        resp = client.post(
            "/whatsapp/simulate", params={"text": "Hola", "from": "584245032990"}
        )
    assert resp.status_code == 404
