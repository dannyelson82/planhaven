"""Passkeys: registration, second factor, passkey-only sign-in, and attacks on each."""

import copy
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from sqlalchemy import text

from app.db.database import Database
from app.main import create_app
from tests.db.conftest import _settings
from tests.db.soft_authenticator import SoftAuthenticator, b64u
from tests.db.test_auth import GOOD_PASSWORD, ORIGIN, _setup_admin
from tests.db.test_mfa import enroll_totp

pytestmark = [pytest.mark.db, pytest.mark.anyio]

RP_ID = "planhaven.example.com"
BASE = "/api/v1/auth/passkeys"


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


async def register(
    client: httpx2.AsyncClient,
    csrf: str,
    device: SoftAuthenticator,
) -> httpx2.Response:
    headers = {"x-csrf-token": csrf}
    opts = await client.post(f"{BASE}/register/options", headers=headers)
    assert opts.status_code == 200, opts.text
    body = opts.json()
    assert body["options"]["authenticatorSelection"]["residentKey"] == "required"
    assert body["options"]["authenticatorSelection"]["userVerification"] == "required"
    return await client.post(
        f"{BASE}/register",
        headers=headers,
        json={
            "challenge_id": body["challenge_id"],
            "credential": device.create(body["options"]),
            "name": "Test phone",
        },
    )


async def passkey_login(
    client: httpx2.AsyncClient, device: SoftAuthenticator, **kwargs: Any
) -> httpx2.Response:
    client.cookies.clear()
    opts = (await client.post(f"{BASE}/login/options")).json()
    return await client.post(
        f"{BASE}/login",
        json={
            "challenge_id": opts["challenge_id"],
            "credential": device.get(opts["options"], **kwargs),
        },
    )


async def test_passkey_as_first_factor_then_passkey_only_sign_in(
    client: httpx2.AsyncClient, db: Database
) -> None:
    csrf = (await _setup_admin(client, db)).json()["csrf_token"]
    device = SoftAuthenticator(RP_ID, ORIGIN)

    registered = await register(client, csrf, device)
    assert registered.status_code == 200, registered.text
    assert len(registered.json()["recovery_codes"]) == 10
    assert (await client.get("/api/v1/auth/sessions")).status_code == 200  # now verified

    login = await passkey_login(client, device)
    assert login.status_code == 200, login.text
    assert login.json()["mfa_verified"] is True
    assert (await client.get("/api/v1/auth/sessions")).status_code == 200
    listed = (await client.get(BASE)).json()
    assert [p["name"] for p in listed] == ["Test phone"]
    assert listed[0]["last_used_at"] is not None


async def test_passkey_as_second_step_after_password(
    client: httpx2.AsyncClient, db: Database
) -> None:
    csrf = (await _setup_admin(client, db)).json()["csrf_token"]
    device = SoftAuthenticator(RP_ID, ORIGIN)
    await register(client, csrf, device)

    client.cookies.clear()
    csrf = (
        await client.post(
            "/api/v1/auth/login", json={"email": "admin@example.com", "password": GOOD_PASSWORD}
        )
    ).json()["csrf_token"]
    headers = {"x-csrf-token": csrf}
    assert (await client.get("/api/v1/auth/sessions")).status_code == 403
    opts = (await client.post(f"{BASE}/verify/options", headers=headers)).json()
    assert opts["options"]["allowCredentials"][0]["id"] == b64u(device.credential_id)
    verified = await client.post(
        f"{BASE}/verify",
        headers=headers,
        json={"challenge_id": opts["challenge_id"], "credential": device.get(opts["options"])},
    )
    assert verified.status_code == 204
    assert (await client.get("/api/v1/auth/sessions")).status_code == 200


async def test_forged_or_foreign_assertions_are_rejected(
    client: httpx2.AsyncClient, db: Database
) -> None:
    csrf = (await _setup_admin(client, db)).json()["csrf_token"]
    device = SoftAuthenticator(RP_ID, ORIGIN)
    await register(client, csrf, device)

    # A phishing site's origin.
    phisher = copy.copy(device)
    phisher.origin = "https://planhaven.example.com.evil.example"
    assert (await passkey_login(client, phisher)).status_code == 401

    # A different key claiming the same credential ID.
    impostor = SoftAuthenticator(RP_ID, ORIGIN)
    impostor.credential_id, impostor.user_handle = device.credential_id, device.user_handle
    assert (await passkey_login(client, impostor)).status_code == 401

    # No user verification (no biometric/PIN).
    assert (await passkey_login(client, device, user_verified=False)).status_code == 401

    # A cloned authenticator replaying an old signature counter.
    assert (await passkey_login(client, device)).status_code == 200
    assert (await passkey_login(client, device, counter=1)).status_code == 401

    async with db.system_transaction() as conn:
        failures = await conn.scalar(
            text(
                "SELECT count(*) FROM audit_events WHERE action = 'login.failed' "
                "AND details->>'method' = 'passkey'"
            )
        )
    assert failures >= 4


async def test_challenges_are_single_use(client: httpx2.AsyncClient, db: Database) -> None:
    csrf = (await _setup_admin(client, db)).json()["csrf_token"]
    device = SoftAuthenticator(RP_ID, ORIGIN)
    await register(client, csrf, device)

    client.cookies.clear()
    opts = (await client.post(f"{BASE}/login/options")).json()
    body = {"challenge_id": opts["challenge_id"], "credential": device.get(opts["options"])}
    assert (await client.post(f"{BASE}/login", json=body)).status_code == 200
    client.cookies.clear()
    body["credential"] = device.get(opts["options"])
    assert (await client.post(f"{BASE}/login", json=body)).status_code == 401


async def test_password_only_session_cannot_add_a_passkey_to_protected_account(
    client: httpx2.AsyncClient, db: Database
) -> None:
    csrf = (await _setup_admin(client, db)).json()["csrf_token"]
    await enroll_totp(client, csrf)
    client.cookies.clear()
    csrf = (
        await client.post(
            "/api/v1/auth/login", json={"email": "admin@example.com", "password": GOOD_PASSWORD}
        )
    ).json()["csrf_token"]
    response = await client.post(f"{BASE}/register/options", headers={"x-csrf-token": csrf})
    assert response.status_code == 403


async def test_last_second_factor_cannot_be_removed(
    client: httpx2.AsyncClient, db: Database
) -> None:
    csrf = (await _setup_admin(client, db)).json()["csrf_token"]
    device = SoftAuthenticator(RP_ID, ORIGIN)
    await register(client, csrf, device)
    passkey_id = (await client.get(BASE)).json()[0]["id"]

    refused = await client.delete(f"{BASE}/{passkey_id}", headers={"x-csrf-token": csrf})
    assert refused.status_code == 400

    await enroll_totp(client, csrf)  # a second factor of another kind; also fresh step-up
    removed = await client.delete(f"{BASE}/{passkey_id}", headers={"x-csrf-token": csrf})
    assert removed.status_code == 204
    assert (await passkey_login(client, device)).status_code == 401
