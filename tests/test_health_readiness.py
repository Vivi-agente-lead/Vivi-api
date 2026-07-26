"""`GET /health` must report 503, naming the failed dependency, when the
database is unreachable at startup — not swallow `init_db()` failures with a
warning and keep answering 200 against a schema-less database.

`app.core.db.init_db` is patched to raise a controlled exception instead of
depending on real Postgres reachability, so these tests are deterministic on
any host.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.core.db as db_module
from app.core.config import settings
from app.main import app


def test_health_returns_503_when_init_db_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")

    async def _boom() -> None:
        raise OSError("could not connect to server: Connection refused")

    monkeypatch.setattr(db_module, "init_db", _boom)

    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["dependency"] == "database"
    assert "Connection refused" in body["detail"]


def test_health_returns_200_when_init_db_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")

    async def _ok() -> None:
        return None

    monkeypatch.setattr(db_module, "init_db", _ok)

    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_is_ready_in_test_env_even_without_calling_init_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`is_test_env` skips `init_db()` entirely (fixtures/doubles own their
    own state), so `/health` must default to ready rather than unreachable."""
    monkeypatch.setattr(settings, "app_env", "test")

    async def _should_never_run() -> None:
        raise AssertionError("init_db must not be called when is_test_env is True")

    monkeypatch.setattr(db_module, "init_db", _should_never_run)

    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
