import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import health as health_service

client = TestClient(create_app())


def test_healthz_reports_ok() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_reveals_no_version() -> None:
    response = client.get("/healthz")

    assert "server" not in response.headers
    assert "version" not in response.text.lower()


def test_api_docs_are_not_served() -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_readyz_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ready() -> bool:
        return True

    monkeypatch.setattr(health_service, "is_ready", ready)

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_not_ready_reveals_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def not_ready() -> bool:
        return False

    monkeypatch.setattr(health_service, "is_ready", not_ready)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not ready"}


def test_database_unreachable_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db import health as db_health

    monkeypatch.setattr(db_health, "SOCKET_DIR", "/nonexistent-planhaven-socket-dir")

    assert asyncio.run(db_health.database_reachable()) is False
