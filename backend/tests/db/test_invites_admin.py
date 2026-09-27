"""Invites, admin account management and notifications (SECURITY.md §7.1, §7.4)."""

import ipaddress
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.db.database import Database
from app.main import create_app
from tests.conftest import make_settings
from tests.db.conftest import _settings
from tests.db.test_auth import GOOD_PASSWORD, ORIGIN, _setup_admin
from tests.db.test_mfa import code_at, enroll_totp

pytestmark = [pytest.mark.db, pytest.mark.anyio]
OTHER_PASSWORD = "a different passphrase entirely"


@pytest.fixture
async def app(owner_db: Database) -> AsyncIterator[FastAPI]:
    async with owner_db.anonymous_transaction() as conn:
        await conn.execute(text("TRUNCATE users, sessions, setup_tokens CASCADE"))
    application = create_app(_settings())
    yield application
    await application.state.db.dispose()


def client_from(app: FastAPI, ip: str = "203.0.113.5") -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app, client=(ip, 1)),
        base_url=ORIGIN,
        headers={"origin": ORIGIN},
    )


async def admin_client(
    app: FastAPI, db: Database
) -> tuple[httpx2.AsyncClient, dict[str, str], str]:
    c = client_from(app)
    csrf = (await _setup_admin(c, db)).json()["csrf_token"]
    secret, _ = await enroll_totp(c, csrf)
    return c, {"x-csrf-token": csrf}, secret


async def invite(c: httpx2.AsyncClient, headers: dict[str, str], **body: Any) -> str:
    r = await c.post("/api/v1/admin/invites", headers=headers, json=body)
    assert r.status_code == 201, r.text
    url: str = r.json()["url"]
    assert url.startswith(f"{ORIGIN}/invite#phv_inv_")
    return url.split("#", 1)[1]


async def accept(
    c: httpx2.AsyncClient,
    token: str,
    email: str = "sam@example.com",
) -> httpx2.Response:
    c.cookies.clear()
    return await c.post(
        "/api/v1/invites/accept",
        json={"token": token, "email": email, "display_name": "Sam", "password": OTHER_PASSWORD},
    )


async def test_invite_creates_a_regular_user_once(app: FastAPI, db: Database) -> None:
    c, headers, _ = await admin_client(app, db)
    token = await invite(c, headers)
    async with client_from(app, "198.51.100.30") as guest:
        assert (await guest.post("/api/v1/invites/check", json={"token": token})).json() == {
            "valid": True,
            "email": None,
        }
        joined = await accept(guest, token)
        assert joined.status_code == 201, joined.text
        assert joined.json()["user"]["is_admin"] is False
        assert joined.json()["mfa_verified"] is False  # must enroll a second factor next
        assert (await accept(guest, token, "other@example.com")).status_code == 400
        assert (await guest.post("/api/v1/invites/check", json={"token": token})).json() == {
            "valid": False,
            "email": None,
        }
    statuses = [i["status"] for i in (await c.get("/api/v1/admin/invites")).json()]
    assert statuses == ["used"]
    await c.aclose()


async def test_invite_bound_to_email_and_revocable(app: FastAPI, db: Database) -> None:
    c, headers, _ = await admin_client(app, db)
    bound = await invite(c, headers, email="Sam@Example.com")
    async with client_from(app, "198.51.100.31") as guest:
        assert (await accept(guest, bound, "mallory@example.com")).status_code == 400
        assert (await accept(guest, bound, "sam@example.com")).status_code == 201

    revoked = await invite(c, headers)
    invite_id = next(
        i["id"] for i in (await c.get("/api/v1/admin/invites")).json() if i["status"] == "pending"
    )
    assert (
        await c.delete(f"/api/v1/admin/invites/{invite_id}", headers=headers)
    ).status_code == 204
    async with client_from(app, "198.51.100.32") as guest:
        assert (await accept(guest, revoked, "x@example.com")).status_code == 400
    await c.aclose()


async def test_admin_area_is_invisible_to_non_admins(app: FastAPI, db: Database) -> None:
    c, headers, _ = await admin_client(app, db)
    token = await invite(c, headers)
    async with client_from(app, "198.51.100.33") as user:
        csrf = (await accept(user, token)).json()["csrf_token"]
        await enroll_totp(user, csrf)
        uh = {"x-csrf-token": csrf}
        assert (await user.get("/api/v1/admin/users")).status_code == 404
        assert (await user.post("/api/v1/admin/invites", headers=uh, json={})).status_code == 404
    await c.aclose()


async def test_admin_actions_need_recent_second_factor(app: FastAPI, db: Database) -> None:
    c, headers, secret = await admin_client(app, db)
    assert (await c.get("/api/v1/admin/users")).status_code == 200
    async with db.system_transaction() as conn:
        await conn.execute(text("UPDATE sessions SET reauth_at = now() - interval '6 minutes'"))
    assert (await c.get("/api/v1/admin/users")).status_code == 403
    assert (
        await c.post(
            "/api/v1/auth/mfa/totp/verify", headers=headers, json={"code": code_at(secret, 1)}
        )
    ).status_code == 204
    assert (await c.get("/api/v1/admin/users")).status_code == 200
    await c.aclose()


async def test_admin_network_restriction(db: Database, owner_db: Database) -> None:
    async with owner_db.anonymous_transaction() as conn:
        await conn.execute(text("TRUNCATE users, sessions, setup_tokens CASCADE"))
    settings = _settings()
    restricted = create_app(
        make_settings(
            db_host=settings.db_host,
            db_port=settings.db_port,
            admin_allowed_cidrs=(ipaddress.ip_network("192.168.1.0/24"),),
        )
    )
    try:
        async with client_from(restricted, "203.0.113.5") as outside:
            csrf = (await _setup_admin(outside, db)).json()["csrf_token"]
            await enroll_totp(outside, csrf)
            assert (await outside.get("/api/v1/admin/users")).status_code == 404
        async with client_from(restricted, "192.168.1.20") as home:
            csrf = (
                await home.post(
                    "/api/v1/auth/login",
                    json={"email": "admin@example.com", "password": GOOD_PASSWORD},
                )
            ).json()["csrf_token"]
            secret = await _secret_for_admin(db)
            await home.post(
                "/api/v1/auth/mfa/totp/verify",
                headers={"x-csrf-token": csrf},
                json={"code": code_at(secret, 1)},
            )
            assert (await home.get("/api/v1/admin/users")).status_code == 200
    finally:
        await restricted.state.db.dispose()


async def _secret_for_admin(db: Database) -> str:
    from app.core.crypto import Keyring
    from tests.conftest import _SECRETS

    keyring = Keyring.from_file(_SECRETS / "master.key")
    async with db.system_transaction() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT t.user_id, t.secret_encrypted FROM totp_credentials t "
                    "JOIN users u ON u.id = t.user_id WHERE u.is_admin"
                )
            )
        ).one()
    return keyring.decrypt(
        "totp-secret", bytes(row.secret_encrypted), f"user:{row.user_id}"
    ).decode()


async def test_disable_and_last_admin_protection(app: FastAPI, db: Database) -> None:
    c, headers, _ = await admin_client(app, db)
    me = (await c.get("/api/v1/auth/session")).json()["user"]["id"]
    assert (
        await c.post(f"/api/v1/admin/users/{me}/disabled", headers=headers, json={"value": True})
    ).status_code == 400
    assert (
        await c.post(f"/api/v1/admin/users/{me}/admin", headers=headers, json={"value": False})
    ).status_code == 400

    token = await invite(c, headers)
    async with client_from(app, "198.51.100.34") as user:
        await accept(user, token)
        sam = next(
            u["id"]
            for u in (await c.get("/api/v1/admin/users")).json()
            if u["email"] == "sam@example.com"
        )
        assert (
            await c.post(
                f"/api/v1/admin/users/{sam}/disabled", headers=headers, json={"value": True}
            )
        ).status_code == 204
        assert (await user.get("/api/v1/auth/session")).status_code == 401  # signed out
        user.cookies.clear()
        assert (
            await user.post(
                "/api/v1/auth/login", json={"email": "sam@example.com", "password": OTHER_PASSWORD}
            )
        ).status_code == 401

        # Promote, then the original admin may step down.
        await c.post(f"/api/v1/admin/users/{sam}/disabled", headers=headers, json={"value": False})
        assert (
            await c.post(f"/api/v1/admin/users/{sam}/admin", headers=headers, json={"value": True})
        ).status_code == 204
        assert (
            await c.post(f"/api/v1/admin/users/{me}/admin", headers=headers, json={"value": False})
        ).status_code == 204
    await c.aclose()


async def test_reset_second_factor(app: FastAPI, db: Database) -> None:
    c, headers, _ = await admin_client(app, db)
    token = await invite(c, headers)
    async with client_from(app, "198.51.100.35") as user:
        csrf = (await accept(user, token)).json()["csrf_token"]
        await enroll_totp(user, csrf)
        sam = next(
            u
            for u in (await c.get("/api/v1/admin/users")).json()
            if u["email"] == "sam@example.com"
        )
        assert sam["has_second_factor"] is True
        assert (
            await c.post(f"/api/v1/admin/users/{sam['id']}/reset-second-factor", headers=headers)
        ).status_code == 204
        assert (await user.get("/api/v1/auth/session")).status_code == 401
        # Next password sign-in may enroll again.
        user.cookies.clear()
        csrf = (
            await user.post(
                "/api/v1/auth/login", json={"email": "sam@example.com", "password": OTHER_PASSWORD}
            )
        ).json()["csrf_token"]
        await enroll_totp(user, csrf)
        kinds = [n["data"].get("change") for n in (await user.get("/api/v1/notifications")).json()]
        assert "second_factor_reset" in kinds
    await c.aclose()


async def test_new_sign_in_notification(app: FastAPI, db: Database) -> None:
    c, headers, _ = await admin_client(app, db)
    async with client_from(app, "198.51.100.99") as elsewhere:
        await elsewhere.post(
            "/api/v1/auth/login", json={"email": "admin@example.com", "password": GOOD_PASSWORD}
        )
    items = (await c.get("/api/v1/notifications")).json()
    new = [n for n in items if n["kind"] == "new_sign_in"]
    assert [n["data"]["ip"] for n in new] == ["198.51.100.99"]
    assert (
        await c.post(f"/api/v1/notifications/{new[0]['id']}/read", headers=headers)
    ).status_code == 204
    # Same address again: no second notification.
    async with client_from(app, "198.51.100.99") as elsewhere:
        await elsewhere.post(
            "/api/v1/auth/login", json={"email": "admin@example.com", "password": GOOD_PASSWORD}
        )
    again = [n for n in (await c.get("/api/v1/notifications")).json() if n["kind"] == "new_sign_in"]
    assert len(again) == 1
    await c.aclose()
