"""Mandatory second factor, recovery codes and step-up (SECURITY.md §7.1)."""

import re
import time
from collections.abc import AsyncIterator
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx2
import pyotp
import pytest
from sqlalchemy import text

from app.db.database import Database
from app.main import create_app
from app.services import auth as auth_service
from app.services import mfa as mfa_service
from tests.db.conftest import _settings
from tests.db.test_auth import GOOD_PASSWORD, ORIGIN, _setup_admin

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def enroll_totp(client: httpx2.AsyncClient, csrf: str) -> tuple[str, list[str]]:
    """Enroll TOTP on the client's session. Returns (secret, recovery codes)."""
    headers = {"x-csrf-token": csrf}
    enroll = await client.post("/api/v1/auth/mfa/totp/enroll", headers=headers)
    assert enroll.status_code == 200, enroll.text
    secret = enroll.json()["secret"]
    uri = urlparse(enroll.json()["otpauth_uri"])
    assert uri.scheme == "otpauth"
    assert parse_qs(uri.query)["issuer"] == ["PlanHaven"]
    confirm = await client.post(
        "/api/v1/auth/mfa/totp/confirm", headers=headers, json={"code": pyotp.TOTP(secret).now()}
    )
    assert confirm.status_code == 200, confirm.text
    return secret, confirm.json()["recovery_codes"]


def code_at(secret: str, steps_from_now: int) -> str:
    return pyotp.TOTP(secret).at(int(time.time()) + steps_from_now * 30)


@pytest.fixture
async def client(owner_db: Database) -> AsyncIterator[httpx2.AsyncClient]:
    async with owner_db.anonymous_transaction() as conn:
        await conn.execute(text("TRUNCATE users, sessions, setup_tokens CASCADE"))
    app = create_app(_settings())
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url=ORIGIN, headers={"origin": ORIGIN}
    ) as c:
        yield c
    await app.state.db.dispose()


async def _login(client: httpx2.AsyncClient) -> str:
    client.cookies.clear()
    response = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": GOOD_PASSWORD}
    )
    assert response.status_code == 200
    csrf: str = response.json()["csrf_token"]
    return csrf


async def test_password_alone_only_reaches_the_second_factor(
    client: httpx2.AsyncClient, db: Database
) -> None:
    csrf = (await _setup_admin(client, db)).json()["csrf_token"]
    headers = {"x-csrf-token": csrf}

    # Partial session: allowed to see itself and enroll, nothing else.
    assert (await client.get("/api/v1/auth/session")).status_code == 200
    assert (await client.get("/api/v1/auth/sessions")).status_code == 403
    assert (
        await client.post("/api/v1/auth/mfa/recovery/regenerate", headers=headers)
    ).status_code == 403

    secret, codes = await enroll_totp(client, csrf)
    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert all(re.fullmatch(r"[A-Z2-7]{4}(-[A-Z2-7]{4}){3}", c) for c in codes)
    assert (await client.get("/api/v1/auth/sessions")).status_code == 200

    # A new sign-in with the password alone is partial again.
    csrf = await _login(client)
    assert (await client.get("/api/v1/auth/sessions")).status_code == 403
    session = (await client.get("/api/v1/auth/session")).json()
    assert session["mfa_verified"] is False

    verify = await client.post(
        "/api/v1/auth/mfa/totp/verify",
        headers={"x-csrf-token": csrf},
        json={"code": code_at(secret, 1)},
    )
    assert verify.status_code == 204
    assert (await client.get("/api/v1/auth/sessions")).status_code == 200


async def test_partial_session_cannot_replace_an_existing_factor(
    client: httpx2.AsyncClient, db: Database
) -> None:
    csrf = (await _setup_admin(client, db)).json()["csrf_token"]
    await enroll_totp(client, csrf)

    csrf = await _login(client)  # someone who only knows the password
    response = await client.post("/api/v1/auth/mfa/totp/enroll", headers={"x-csrf-token": csrf})
    assert response.status_code == 403


async def test_totp_codes_cannot_be_replayed(client: httpx2.AsyncClient, db: Database) -> None:
    csrf = (await _setup_admin(client, db)).json()["csrf_token"]
    secret, _ = await enroll_totp(client, csrf)
    code = code_at(secret, 1)  # later step than the one used to enroll

    csrf = await _login(client)
    headers = {"x-csrf-token": csrf}
    assert (
        await client.post("/api/v1/auth/mfa/totp/verify", headers=headers, json={"code": code})
    ).status_code == 204

    csrf = await _login(client)
    replay = await client.post(
        "/api/v1/auth/mfa/totp/verify", headers={"x-csrf-token": csrf}, json={"code": code}
    )
    assert replay.status_code == 400


async def test_five_wrong_codes_end_the_session(client: httpx2.AsyncClient, db: Database) -> None:
    csrf = (await _setup_admin(client, db)).json()["csrf_token"]
    await enroll_totp(client, csrf)
    csrf = await _login(client)
    headers = {"x-csrf-token": csrf}

    for attempt in range(1, 6):
        response = await client.post(
            "/api/v1/auth/mfa/totp/verify", headers=headers, json={"code": "000000"}
        )
        assert response.status_code == 400
        if attempt == 5:
            assert "Sign in again" in response.json()["detail"]
    assert (await client.get("/api/v1/auth/session")).status_code == 401


async def test_recovery_codes_work_once(client: httpx2.AsyncClient, db: Database) -> None:
    csrf = (await _setup_admin(client, db)).json()["csrf_token"]
    _, codes = await enroll_totp(client, csrf)

    csrf = await _login(client)
    used = await client.post(
        "/api/v1/auth/mfa/recovery/verify",
        headers={"x-csrf-token": csrf},
        json={"code": codes[0].lower().replace("-", " ")},
    )
    assert used.status_code == 200
    assert used.json() == {"recovery_codes_remaining": 9}

    csrf = await _login(client)
    again = await client.post(
        "/api/v1/auth/mfa/recovery/verify", headers={"x-csrf-token": csrf}, json={"code": codes[0]}
    )
    assert again.status_code == 400


async def test_step_up_expires(client: httpx2.AsyncClient, db: Database) -> None:
    csrf = (await _setup_admin(client, db)).json()["csrf_token"]
    secret, _ = await enroll_totp(client, csrf)
    headers = {"x-csrf-token": csrf}
    assert (
        await client.post("/api/v1/auth/mfa/recovery/regenerate", headers=headers)
    ).status_code == 200

    async with db.system_transaction() as conn:
        await conn.execute(text("UPDATE sessions SET reauth_at = now() - interval '6 minutes'"))
    stale = await client.post("/api/v1/auth/mfa/recovery/regenerate", headers=headers)
    assert stale.status_code == 403
    assert "Confirm it's you" in stale.json()["detail"]

    assert (
        await client.post(
            "/api/v1/auth/mfa/totp/verify", headers=headers, json={"code": code_at(secret, 1)}
        )
    ).status_code == 204
    assert (
        await client.post("/api/v1/auth/mfa/recovery/regenerate", headers=headers)
    ).status_code == 200


async def test_totp_secret_is_encrypted_at_rest(client: httpx2.AsyncClient, db: Database) -> None:
    csrf = (await _setup_admin(client, db)).json()["csrf_token"]
    secret, codes = await enroll_totp(client, csrf)
    async with db.system_transaction() as conn:
        stored = bytes(await conn.scalar(text("SELECT secret_encrypted FROM totp_credentials")))
        result = await conn.execute(text("SELECT code_hash FROM recovery_codes"))
        raw_hashes: list[bytes] = list(result.scalars())
        stored_codes = [bytes(h) for h in raw_hashes]
    assert secret.encode() not in stored
    assert all(c.replace("-", "").encode() not in h for c in codes for h in stored_codes)


async def test_session_list_and_revoke(client: httpx2.AsyncClient, db: Database) -> None:
    csrf = (await _setup_admin(client, db)).json()["csrf_token"]
    await enroll_totp(client, csrf)
    other = await auth_service.login(
        db, email="admin@example.com", password=GOOD_PASSWORD, ip="198.51.100.7", user_agent="phone"
    )
    headers = {"x-csrf-token": csrf}

    sessions = (await client.get("/api/v1/auth/sessions")).json()
    assert len(sessions) == 2
    assert sum(s["current"] for s in sessions) == 1
    theirs = next(s for s in sessions if not s["current"])
    assert theirs["ip"] == "198.51.100.7"

    assert (
        await client.delete(f"/api/v1/auth/sessions/{theirs['id']}", headers=headers)
    ).status_code == 204
    assert await auth_service.authenticate(db, other.token) is None
    assert (
        await client.delete(f"/api/v1/auth/sessions/{theirs['id']}", headers=headers)
    ).status_code == 404


def test_matching_step_tolerates_one_step_of_clock_skew() -> None:
    secret = pyotp.random_base32()
    now = 1_800_000_000.0
    totp = pyotp.TOTP(secret)
    for offset, ok in ((-2, False), (-1, True), (0, True), (1, True), (2, False)):
        code = totp.at(int(now) + offset * 30)
        assert (mfa_service._matching_step(secret, code, now) is not None) is ok, offset


def test_step_up_window() -> None:
    assert timedelta(minutes=5) == auth_service.STEP_UP_WINDOW
