"""Web Push: the allowlist, the encryption a browser can open, the VAPID signature, and how
push service answers are handled (no network: the HTTP opener is replaced)."""

import base64
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime, time
from typing import Any

import http_ece  # type: ignore[import-untyped]
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02  # type: ignore[import-untyped]

from app.push import webpush
from app.services.notifications import GROUPS, Settings, in_quiet_hours, payload, render


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _browser() -> tuple[ec.EllipticCurvePrivateKey, bytes, webpush.Target]:
    key = ec.generate_private_key(ec.SECP256R1())
    auth = b"0123456789abcdef"
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    target = webpush.Target("https://fcm.googleapis.com/fcm/send/abc", _b64(public), _b64(auth))
    return key, auth, target


def _sender() -> webpush.Sender:
    pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return webpush.Sender(pem, "https://planhaven.example.com")


@pytest.mark.parametrize(
    ("endpoint", "ok"),
    [
        ("https://fcm.googleapis.com/fcm/send/x", True),
        ("https://updates.push.services.mozilla.com/wpush/v2/x", True),
        ("https://web.push.apple.com/QK2x", True),
        ("https://wns2-bl2p.notify.windows.com/w/?token=x", True),
        ("http://fcm.googleapis.com/fcm/send/x", False),  # not HTTPS
        ("https://fcm.googleapis.com:8443/x", False),  # another port
        ("https://evil.example.com/x", False),
        ("https://fcm.googleapis.com.evil.example.com/x", False),
        ("https://user@fcm.googleapis.com/x", False),
        ("https://notify.windows.com.example/x", False),
        ("https://127.0.0.1/x", False),
        ("https://[::1]/x", False),
        ("https://fcm.googleapis.com/" + "x" * 1000, False),
    ],
)
def test_only_known_push_services(endpoint: str, ok: bool) -> None:
    assert webpush.endpoint_allowed(endpoint) is ok


def test_keys_are_checked() -> None:
    _, _, target = _browser()
    assert webpush.keys_valid(target.p256dh, target.auth)
    assert not webpush.keys_valid(target.p256dh, _b64(b"short"))
    assert not webpush.keys_valid(_b64(b"\x04" + b"\x00" * 64), target.auth)  # not on the curve
    assert not webpush.keys_valid("!!!", target.auth)


class _Response:
    status = 201

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self, n: int) -> bytes:
        return b""


def test_the_browser_can_open_it_and_the_signature_checks_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key, auth, target = _browser()
    sent: list[urllib.request.Request] = []

    def fake_open(request: urllib.request.Request, timeout: float) -> _Response:
        assert timeout == webpush.TIMEOUT
        sent.append(request)
        return _Response()

    monkeypatch.setattr(webpush._opener, "open", fake_open)
    body = payload("task_due", {"title": "Change oil", "project_id": "p", "project_title": "Boat"})
    assert _sender().send(target, body) == 201

    request = sent[0]
    assert request.full_url == target.endpoint
    headers = {k.lower(): v for k, v in request.header_items()}
    assert headers["content-encoding"] == "aes128gcm"
    assert headers["ttl"] == str(webpush.TTL)
    assert isinstance(request.data, bytes)
    assert b"Change oil" not in request.data  # encrypted
    opened = http_ece.decrypt(request.data, private_key=key, auth_secret=auth, version="aes128gcm")
    assert json.loads(opened) == {
        "title": "Due today: Change oil",
        "body": "Boat",
        "url": "/projects/p",
    }
    assert Vapid02.verify(headers["authorization"])


def test_gone_devices_and_refusals(monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, target = _browser()

    def answer(code: int) -> Any:
        def fake_open(request: urllib.request.Request, timeout: float) -> Any:
            raise urllib.error.HTTPError(request.full_url, code, "x", {}, None)  # type: ignore[arg-type]

        return fake_open

    sender = _sender()
    monkeypatch.setattr(webpush._opener, "open", answer(410))
    assert sender.send(target, b"{}") == 410
    for code in (301, 400, 429, 500):  # redirects are never followed
        monkeypatch.setattr(webpush._opener, "open", answer(code))
        with pytest.raises(webpush.PushError):
            sender.send(target, b"{}")
    with pytest.raises(webpush.PushError):
        sender.send(webpush.Target("https://evil.example.com/x", target.p256dh, target.auth), b"{}")
    with pytest.raises(webpush.PushError):
        sender.send(target, b"x" * (webpush.MAX_PAYLOAD + 1))


def _quiet(start: str, end: str, tz: str = "America/Toronto") -> Settings:
    prefs = dict.fromkeys(GROUPS, "push")
    return Settings(prefs, time.fromisoformat(start), time.fromisoformat(end), tz, True)


def test_quiet_hours_in_the_persons_time_zone() -> None:
    night = _quiet("22:00", "07:00")
    # 03:00 UTC is 23:00 in Toronto (EDT): quiet until 07:00 Toronto, 11:00 UTC.
    assert in_quiet_hours(night, datetime(2026, 10, 2, 3, tzinfo=UTC)) == datetime(
        2026, 10, 2, 11, tzinfo=UTC
    )
    # 10:00 Toronto (14:00 UTC): not quiet.
    assert in_quiet_hours(night, datetime(2026, 10, 2, 14, tzinfo=UTC)) is None
    # Daytime quiet hours (13:00 to 15:00), at 14:00 Toronto.
    lunch = _quiet("13:00", "15:00")
    assert in_quiet_hours(lunch, datetime(2026, 10, 2, 18, tzinfo=UTC)) == datetime(
        2026, 10, 2, 19, tzinfo=UTC
    )


def test_wording_holds_names_only() -> None:
    shared = render("shared_with_you", {"title": "Boat", "by": "Ann", "project_id": "p1"})
    assert (shared.title, shared.url) == ("Ann shared “Boat” with you", "/projects/p1")
    assert render("unknown_kind", {"x": "y"}).url == "/notifications"
    assert render("new_sign_in", {"ip": "203.0.113.5"}).body.startswith("If this wasn't you")
    assert len(payload("task_due", {"title": "x" * 1000})) < webpush.MAX_PAYLOAD
