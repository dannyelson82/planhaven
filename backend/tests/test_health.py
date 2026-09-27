from fastapi.testclient import TestClient

from app.main import create_app

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
