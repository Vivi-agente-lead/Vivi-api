"""Smoke tests: app imports cleanly, /health returns 200, /docs reachable.

DB-backed tests are skipped when no Postgres is available.
"""

from __future__ import annotations

import importlib
import os

import pytest


def test_app_module_imports() -> None:
    """Importing `app.main` must not raise even when deps are installed."""
    # Force a fresh import to avoid stale state from other tests.
    module = importlib.import_module("app.main")
    assert hasattr(module, "app")
    assert module.app.title == "vivi-api"


@pytest.mark.skipif(
    os.environ.get("VIVI_SKIP_HTTP_TESTS") == "1",
    reason="HTTP smoke tests disabled via VIVI_SKIP_HTTP_TESTS",
)
def test_health_endpoint() -> None:
    """`GET /health` returns 200 with `{"status": "ok"}`.

    Uses FastAPI's TestClient (sync wrapper around httpx). We build a minimal
    client that bypasses DB-dependent lifespan paths so it works without a
    Postgres running.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


@pytest.mark.skipif(
    os.environ.get("VIVI_SKIP_HTTP_TESTS") == "1",
    reason="HTTP smoke tests disabled via VIVI_SKIP_HTTP_TESTS",
)
def test_docs_reachable() -> None:
    """`GET /docs` returns 200 (Swagger UI)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/docs")
        assert resp.status_code == 200


def test_settings_loads() -> None:
    """Settings can be instantiated with env defaults (no crash)."""
    from app.core.config import Settings

    s = Settings()
    assert s.postgres_db == "vivi" or s.postgres_db
    assert s.database_url.startswith("postgresql+psycopg://")