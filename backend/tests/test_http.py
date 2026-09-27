import ipaddress
import json
import logging
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from starlette.types import Message, Receive, Scope, Send

from app.core.http import CSP, ProxyHeadersMiddleware, resolve_client_ip
from app.core.logging import JSONFormatter
from tests.conftest import make_settings

TRUSTED = (ipaddress.ip_network("192.0.2.0/24"), ipaddress.ip_network("2001:db8::/32"))

EXPECTED_HEADERS = {
    "content-security-policy": CSP,
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(self), microphone=(), geolocation=(), payment=(), usb=()",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "strict-transport-security": "max-age=31536000; includeSubDomains",
}


class Item(BaseModel):
    name: str = Field(max_length=10)


@pytest.fixture
def app(settings: object) -> FastAPI:
    from app.main import create_app

    app = create_app(make_settings())

    @app.post("/echo")
    async def echo(item: Item) -> dict[str, str]:
        return {"name": item.name}

    # POST: GET paths the API doesn't know are served the web app shell.
    @app.post("/boom")
    async def boom() -> None:
        raise RuntimeError("secret detail phv_pat_" + "a" * 40)

    return app


# ---------------------------------------------------------------- security headers


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [("GET", "/healthz", 200), ("GET", "/nope", 404), ("POST", "/boom", 500)],
)
def test_security_headers_on_every_response(
    client: TestClient, method: str, path: str, status: int
) -> None:
    response = client.request(method, path)

    assert response.status_code == status
    for name, value in EXPECTED_HEADERS.items():
        assert response.headers.get(name) == value, name
    assert "server" not in response.headers
    assert "x-powered-by" not in response.headers


def test_no_hsts_without_https() -> None:
    from app.main import create_app

    client = TestClient(
        create_app(make_settings(base_url="http://planhaven.lan", public_mode=False))
    )

    assert "strict-transport-security" not in client.get("/healthz").headers


def test_request_id_is_fresh_and_ignores_client_value(client: TestClient) -> None:
    first = client.get("/healthz", headers={"X-Request-ID": "injected\nvalue"})
    second = client.get("/healthz")

    rid = first.headers["x-request-id"]
    assert len(rid) == 32
    assert rid != "injected\nvalue"
    assert rid != second.headers["x-request-id"]


# ---------------------------------------------------------------- errors


def test_not_found_is_problem_json(client: TestClient) -> None:
    response = client.get("/nope")

    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {"type": "about:blank", "title": "Not Found", "status": 404}


def test_server_error_reveals_nothing(client: TestClient) -> None:
    response = client.post("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "type": "about:blank",
        "title": "Internal Server Error",
        "status": 500,
    }


def test_validation_error_does_not_echo_input(client: TestClient) -> None:
    secret = "x" * 50
    response = client.post("/echo", json={"name": secret})

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == 422
    assert body["errors"] == [{"loc": ["body", "name"], "type": "string_too_long"}]
    assert secret not in response.text


# ---------------------------------------------------------------- body size limit


def test_rejects_declared_oversize_body(client: TestClient) -> None:
    response = client.post("/echo", content=b"{" + b" " * 2000 + b"}")

    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["content-security-policy"] == CSP


def test_rejects_streamed_oversize_body_without_length(client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(10):
            yield b" " * 200

    response = client.post("/echo", content=chunks())

    assert response.status_code == 413


def test_accepts_body_within_limit(client: TestClient) -> None:
    response = client.post("/echo", json={"name": "ok"})

    assert response.status_code == 200
    assert response.json() == {"name": "ok"}


def test_rejects_malformed_content_length(client: TestClient) -> None:
    response = client.post("/echo", headers={"content-length": "abc"}, content=b"{}")

    assert response.status_code == 400


# ---------------------------------------------------------------- client IP


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        # Direct connection from the internet: header ignored entirely.
        ("203.0.113.5", ["1.2.3.4"], "203.0.113.5"),
        # Through the trusted proxy: the proxy appended the real client.
        ("192.0.2.10", ["198.51.100.7"], "198.51.100.7"),
        # Client sent a fake header; the proxy appended the real address after it.
        ("192.0.2.10", ["1.2.3.4, 198.51.100.7"], "198.51.100.7"),
        # Chained trusted proxies are skipped.
        ("192.0.2.10", ["198.51.100.7, 192.0.2.20"], "198.51.100.7"),
        # Multiple headers are combined in order.
        ("192.0.2.10", ["1.2.3.4", "198.51.100.7"], "198.51.100.7"),
        # Malformed entry stops the walk at the last trusted hop.
        ("192.0.2.10", ["198.51.100.7, garbage"], "192.0.2.10"),
        # No header: the proxy itself.
        ("192.0.2.10", [], "192.0.2.10"),
        # IPv6.
        ("2001:db8::1", ["2001:db8:ffff::2, 2600::1"], "2600::1"),
    ],
)
def test_resolve_client_ip(peer: str, forwarded: list[str], expected: str) -> None:
    assert resolve_client_ip(peer, forwarded, TRUSTED) == expected


async def _run_proxy_middleware(peer: str, headers: list[tuple[bytes, bytes]]) -> Scope:
    seen: dict[str, Scope] = {}

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen["scope"] = scope

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        pass

    middleware = ProxyHeadersMiddleware(app, make_settings(trusted_proxies=TRUSTED))
    scope: Scope = {
        "type": "http",
        "scheme": "http",
        "client": (peer, 1234),
        "headers": headers,
    }
    await middleware(scope, receive, send)
    return seen["scope"]


async def _scope_for(peer: str, headers: list[tuple[bytes, bytes]]) -> Scope:
    return await _run_proxy_middleware(peer, headers)


def test_proxy_middleware_trusted_peer() -> None:
    import asyncio

    scope = asyncio.run(
        _scope_for(
            "192.0.2.10",
            [(b"x-forwarded-for", b"198.51.100.7"), (b"x-forwarded-proto", b"https")],
        )
    )

    assert scope["client"][0] == "198.51.100.7"
    assert scope["scheme"] == "https"


def test_proxy_middleware_untrusted_peer_ignores_headers() -> None:
    import asyncio

    scope = asyncio.run(
        _scope_for(
            "203.0.113.5",
            [(b"x-forwarded-for", b"198.51.100.7"), (b"x-forwarded-proto", b"https")],
        )
    )

    assert scope["client"][0] == "203.0.113.5"
    assert scope["scheme"] == "http"


# ---------------------------------------------------------------- access log


def test_access_log_redacts_and_omits_query(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="planhaven.access")

    client.get("/ics/phv_ics_" + "b" * 40 + ".ics?token=abc")

    records = [r for r in caplog.records if r.name == "planhaven.access"]
    assert records
    entry = json.loads(JSONFormatter().format(records[-1]))
    assert entry["path"] == "/ics/[redacted]"
    assert entry["status"] == 404
    assert "abc" not in json.dumps(entry)
    assert "phv_ics_" not in json.dumps(entry)


def test_unhandled_error_is_logged_without_message(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    client.post("/boom")

    records = [r for r in caplog.records if r.name == "planhaven.errors"]
    assert records
    entry = json.dumps(json.loads(JSONFormatter().format(records[-1])))
    assert "RuntimeError" in entry
    assert "secret detail" not in entry
    assert "phv_pat_" not in entry
