"""Sending one Web Push message (ADR 0018, SECURITY.md §7.8).

The payload is encrypted for the browser (RFC 8291, `http_ece`) and the request is signed with
our VAPID key (RFC 8292, `py_vapid`): vetted libraries, no crypto of our own. The endpoint was
given to us by the browser, so it's only used when its host is a known push service, over
HTTPS on the standard port, without following redirects, with a timeout and a cap on the
response read.
"""

import base64
import binascii
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import http_ece  # type: ignore[import-untyped]
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02  # type: ignore[import-untyped]

# Push services of the browsers people use: Chrome/Edge/Android (Google), Firefox (Mozilla),
# Safari and iPhone home-screen apps (Apple), Windows (Microsoft).
ALLOWED_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com")
ALLOWED_SUFFIXES = (".push.apple.com", ".notify.windows.com", ".push.services.mozilla.com")
MAX_PAYLOAD = 3000  # well under the 4 KB the services accept, after encryption overhead
TIMEOUT = 10.0
TTL = 24 * 3600  # a reminder that can't be delivered within a day isn't worth delivering


class PushError(Exception):
    """The push service refused the message or couldn't be reached."""


def endpoint_allowed(endpoint: str) -> bool:
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return (
        parts.scheme == "https"
        and port in (None, 443)
        and parts.username is None
        and parts.password is None
        and len(endpoint) <= 1000
        and (host in ALLOWED_HOSTS or any(host.endswith(s) for s in ALLOWED_SUFFIXES))
    )


def _b64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def keys_valid(p256dh: str, auth: str) -> bool:
    """The browser's public key (an uncompressed P-256 point) and its 16-byte auth secret."""
    if len(p256dh) > 200 or len(auth) > 100:
        return False
    try:
        public = _b64(p256dh)
        secret = _b64(auth)
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
    except ValueError, binascii.Error:
        return False
    return len(public) == 65 and len(secret) == 16


@dataclass(frozen=True, slots=True)
class Target:
    endpoint: str
    p256dh: str
    auth: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # a redirect is an error, never followed


_opener = urllib.request.build_opener(_NoRedirect)


class Sender:
    """Signs and sends with the server's VAPID key (from /config/secrets)."""

    def __init__(self, private_pem: bytes, subject: str) -> None:
        self._vapid = Vapid02.from_pem(private_pem)
        self._subject = subject  # https://<BASE_URL host>: who to contact about our pushes

    @classmethod
    def from_dir(cls, secrets_dir: str, subject: str) -> Sender:
        return cls((Path(secrets_dir) / "vapid_private.pem").read_bytes(), subject)

    def send(self, target: Target, payload: bytes) -> int:
        """Send one message (blocking; run it in a thread). Returns the push service's status
        code for 2xx, 404 and 410; raises PushError otherwise."""
        if not endpoint_allowed(target.endpoint):
            raise PushError("endpoint not allowed")
        if len(payload) > MAX_PAYLOAD:
            raise PushError("payload too large")
        body = http_ece.encrypt(
            payload,
            salt=os.urandom(16),
            private_key=ec.generate_private_key(ec.SECP256R1()),
            dh=_b64(target.p256dh),
            auth_secret=_b64(target.auth),
            version="aes128gcm",
        )
        parts = urlsplit(target.endpoint)
        claims = {
            "aud": f"https://{parts.hostname}",
            "exp": int(time.time()) + 12 * 3600,
            "sub": self._subject,
        }
        headers = {
            **self._vapid.sign(claims),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(TTL),
            "Urgency": "normal",
        }
        request = urllib.request.Request(  # noqa: S310 (https and an allowlisted host only)
            target.endpoint, data=body, headers=headers, method="POST"
        )
        try:
            with _opener.open(request, timeout=TIMEOUT) as response:
                response.read(4096)
                return int(response.status)
        except urllib.error.HTTPError as exc:
            exc.close()  # the error response body isn't read
            if exc.code in (404, 410):
                return exc.code  # the browser unsubscribed: forget this device
            raise PushError(f"push service answered {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PushError(type(exc).__name__) from None
