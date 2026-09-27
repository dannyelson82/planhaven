from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings


def _client(tmp_path: Path) -> TestClient:
    (tmp_path / "static").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>Planhaven</title>")
    (tmp_path / "static" / "app-abc123.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("outside assets")
    return TestClient(create_app(make_settings(frontend_dir=str(tmp_path))))


def test_serves_index_for_app_paths(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path in ("/", "/projects", "/projects/123/tasks", "/invite", "/assets", "/assets/1"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "Planhaven" in response.text
        assert response.headers["cache-control"] == "no-cache"
        assert "content-security-policy" in response.headers


def test_serves_hashed_assets_immutably(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/static/app-abc123.js")
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


def test_no_path_traversal_or_api_shadowing(tmp_path: Path) -> None:
    client = _client(tmp_path)
    # Clients may normalise "../" away (then the app shell is served); either way the file
    # outside assets/ must never be returned.
    for path in (
        "/static/../secret.txt",
        "/static/%2e%2e/secret.txt",
        "/static/..%2fsecret.txt",
        "/static/%2e%2e%2fsecret.txt",
    ):
        assert "outside assets" not in client.get(path).text, path
    assert client.get("/static/missing.js").status_code == 404
    assert client.get("/api/v1/nope").status_code == 404
    assert client.get("/api/v1/nope").headers["content-type"] == "application/problem+json"
