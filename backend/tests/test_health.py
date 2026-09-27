import asyncio

import pytest
from fastapi.testclient import TestClient

from app.services import health as health_service


def test_healthz_reports_ok(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_reveals_no_version(client: TestClient) -> None:
    response = client.get("/healthz")

    assert "server" not in response.headers
    assert "version" not in response.text.lower()


def test_api_docs_are_not_served(client: TestClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_readyz_ready(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def ready(_: object) -> bool:
        return True

    monkeypatch.setattr(health_service, "is_ready", ready)

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_not_ready_reveals_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def not_ready(_: object) -> bool:
        return False

    monkeypatch.setattr(health_service, "is_ready", not_ready)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not ready"}


def test_database_unreachable_is_not_ready() -> None:
    from app.db.database import Database
    from app.db.health import database_ready
    from tests.conftest import make_settings

    db = Database(make_settings(db_host="/nonexistent-planhaven-socket-dir"))
    assert asyncio.run(database_ready(db, None)) is False
