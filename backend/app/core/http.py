"""HTTP safety middleware (SECURITY.md §7.10, §7.11). Pure ASGI, applied to every request.

Order, outermost first: request ID → client IP from trusted proxies → access log → security
headers → unhandled errors → body size limit → application. So every response, including a
413 or a 500, is logged and carries the security headers.
"""

import ipaddress
import json
import logging
import re
import time
import uuid
from collections.abc import Iterable
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import IPNetwork, Settings
from app.core.logging import redact_path, request_id_var

access_log = logging.getLogger("planhaven.access")
error_log = logging.getLogger("planhaven.errors")

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# React Aria injects one fixed stylesheet (touch-action for pressable elements, so taps and
# scrolling behave on phones). It is allowed by its exact SHA-256 hash and nothing else; the
# browser end-to-end test fails if the injected text ever changes (SECURITY.md §7.10).
REACT_ARIA_STYLE_HASH = "'sha256-38RhXrc7EdReTKsOm23ZPOCUgniTUUcjky8QOOrQx6o='"

CSP = (
    "default-src 'self'; script-src 'self'; "
    f"style-src 'self' {REACT_ARIA_STYLE_HASH}; img-src 'self' data: blob:; "
    "font-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
    "frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; "
    "object-src 'none'; upgrade-insecure-requests"
)

SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (
        b"permissions-policy",
        b"camera=(self), microphone=(), geolocation=(), payment=(), usb=()",
    ),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
)
CSP_HEADER = b"content-security-policy"
# For served files: nothing in them may load, run or be framed (SECURITY.md §7.5).
FILE_CSP = "default-src 'none'; sandbox; frame-ancestors 'none'"
HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
_STRIPPED = {b"server", b"x-powered-by"}


def _header(scope: Scope, name: bytes) -> list[str]:
    return [v.decode("latin-1") for k, v in scope.get("headers", []) if k == name]


def _parse_ip(value: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def _trusted(ip: IPAddress, networks: Iterable[IPNetwork]) -> bool:
    return any(ip in net for net in networks)


def resolve_client_ip(
    peer: str | None, forwarded_for: list[str], trusted: tuple[IPNetwork, ...]
) -> str | None:
    """The real client address. `X-Forwarded-For` is honoured only when the connecting peer is
    a trusted proxy, and is read right to left, skipping trusted proxies, so a client can't
    choose its own address by sending the header itself."""
    peer_ip = _parse_ip(peer) if peer else None
    if peer_ip is None or not _trusted(peer_ip, trusted):
        return peer
    hops = [h for header in forwarded_for for h in header.split(",") if h.strip()]
    client = peer_ip
    for hop in reversed(hops):
        ip = _parse_ip(hop)
        if ip is None:
            break  # malformed chain: stop at the last address we could trust
        client = ip
        if not _trusted(ip, trusted):
            break
    return str(client)


class ProxyHeadersMiddleware:
    """Rewrites the ASGI client address and scheme from trusted proxy headers only."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.trusted = settings.trusted_proxies

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            peer = client[0] if client else None
            real = resolve_client_ip(peer, _header(scope, b"x-forwarded-for"), self.trusted)
            peer_ip = _parse_ip(peer) if peer else None
            if real != peer:
                scope["client"] = (real, 0)
            if peer_ip is not None and _trusted(peer_ip, self.trusted):
                proto = _header(scope, b"x-forwarded-proto")
                if proto:
                    last = proto[-1].split(",")[-1].strip().lower()
                    if last in ("http", "https"):
                        scope["scheme"] = (
                            last
                            if scope["type"] == "http"
                            else ("wss" if last == "https" else "ws")
                        )
        await self.app(scope, receive, send)


class RequestIDMiddleware:
    """A fresh random ID per request, in logs and the `X-Request-ID` response header. Incoming
    IDs are ignored so clients can't inject values into logs."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex
        token = request_id_var.set(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)


class SecurityHeadersMiddleware:
    """Adds the SECURITY.md §7.10 headers to every response and removes server banners.

    A response may carry its own, stricter Content-Security-Policy (file downloads use
    `default-src 'none'; sandbox`); every other header is always replaced."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.headers = [*SECURITY_HEADERS, *([HSTS] if settings.base_scheme == "https" else [])]
        self.names = {name for name, _ in self.headers}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                own_csp = any(k.lower() == CSP_HEADER for k, _ in headers)
                replaced = self.names - {CSP_HEADER} if own_csp else self.names
                kept = [
                    (k, v)
                    for k, v in headers
                    if k.lower() not in _STRIPPED and k.lower() not in replaced
                ]
                added = [h for h in self.headers if not (own_csp and h[0] == CSP_HEADER)]
                message["headers"] = [*kept, *added]
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def _send_problem(send: Send, status: int, title: str) -> None:
    body = json.dumps({"type": "about:blank", "title": title, "status": status}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


# File uploads (raw body): project attachments (POST), asset and contact photos (PUT), and
# contact cards (POST /contacts/import). Every other body gets the (small) JSON limit.
_UPLOAD_PATH = re.compile(
    r"/api/v1/(projects/[0-9a-fA-F-]{36}/attachments|(assets|contacts)/[0-9a-fA-F-]{36}/photo"
    r"|contacts/import)"
)


class BodySizeLimitMiddleware:
    """Rejects request bodies over the limit with 413, checking both the declared length and
    the bytes actually received (the declared length can be missing or wrong)."""

    def __init__(self, app: ASGIApp, max_bytes: int, upload_max_bytes: int | None = None) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.upload_max_bytes = upload_max_bytes or max_bytes

    def _limit(self, scope: Scope) -> int:
        # File uploads (raw body) get the MAX_UPLOAD_MB limit; everything else the JSON limit.
        if scope.get("method") in ("POST", "PUT") and _UPLOAD_PATH.fullmatch(scope.get("path", "")):
            return self.upload_max_bytes
        return self.max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        max_bytes = self._limit(scope)
        declared = _header(scope, b"content-length")
        if declared:
            try:
                too_big = int(declared[0]) > max_bytes
            except ValueError:
                await _send_problem(send, 400, "Bad Request")
                return
            if too_big:
                await _send_problem(send, 413, "Content Too Large")
                return

        received = 0
        started = False
        rejected = False

        async def counting_receive() -> Message:
            # On overflow, answer 413 ourselves and tell the app the client went away, so it
            # stops reading. (Raising here wouldn't work: frameworks turn body-read errors
            # into a generic 400.)
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    rejected = True
                    if not started:
                        await _send_problem(send, 413, "Content Too Large")
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return  # the 413 has been sent; drop whatever the app tries to answer
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, counting_receive, tracking_send)


class UnhandledErrorMiddleware:
    """Turns unexpected exceptions into a bare 500 problem response *inside* the middleware
    stack, so error responses still get security headers and an access-log line. (Starlette's
    own last-resort handler sits outside all middleware.)"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            error_log.error("unhandled error", exc_info=exc)
            if not started:
                await _send_problem(send, 500, "Internal Server Error")


class AccessLogMiddleware:
    """One structured line per request. Paths are redacted (tokens can appear in URLs) and
    query strings are never logged."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = 500

        async def capture_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            client: Any = scope.get("client")
            access_log.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": redact_path(scope.get("path", "")),
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                    "client_ip": client[0] if client else None,
                },
            )
