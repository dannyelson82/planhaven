"""Sign-in, setup and session security (SECURITY.md §7.1, §7.2), against a real database."""

import uuid
from collections.abc import AsyncIterator

import httpx2
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.auth import passwords
from app.db.database import Database
from app.main import create_app
from app.services import auth as auth_service
from tests.db.conftest import _settings

pytestmark = [pytest.mark.db, pytest.mark.anyio]

ORIGIN = "https://planhaven.example.com"
COOKIE = "__Host-planhaven_session"
GOOD_PASSWORD = "correct horse battery staple 42"


@pytest.fixture
async def clean(owner_db: Database) -> None:
    async with owner_db.anonymous_transaction() as conn:
        await conn.execute(text("TRUNCATE users, sessions, setup_tokens CASCADE"))


@pytest.fixture
async def client(clean: None) -> AsyncIterator[httpx2.AsyncClient]:
    app = create_app(_settings())
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(
        transport=transport, base_url=ORIGIN, headers={"origin": ORIGIN}
    ) as c:
        yield c
    await app.state.db.dispose()


async def _setup_admin(client: httpx2.AsyncClient, db: Database) -> httpx2.Response:
    token = await auth_service.issue_setup_token(db)
    assert token is not None
    return await client.post(
        "/api/v1/setup",
        json={
            "setup_token": token,
            "email": "Admin@Example.com",
            "display_name": "Admin",
            "password": GOOD_PASSWORD,
        },
    )


async def test_setup_flow(client: httpx2.AsyncClient, db: Database) -> None:
    assert (await client.get("/api/v1/setup")).json() == {"setup_required": True}

    bad = await client.post(
        "/api/v1/setup",
        json={
            "setup_token": "phv_setup_wrong",
            "email": "a@example.com",
            "display_name": "A",
            "password": GOOD_PASSWORD,
        },
    )
    assert bad.status_code == 400

    response = await _setup_admin(client, db)
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "admin@example.com"
    assert body["user"]["is_admin"] is True
    assert body["mfa_verified"] is False
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert flag.lower() in cookie.lower(), flag

    assert (await client.get("/api/v1/setup")).json() == {"setup_required": False}
    assert await auth_service.issue_setup_token(db) is None


async def test_setup_token_works_once_and_expires(client: httpx2.AsyncClient, db: Database) -> None:
    token = await auth_service.issue_setup_token(db)
    assert token is not None
    # (The owner role can't do this: FORCE ROW LEVEL SECURITY applies to it too.)
    async with db.system_transaction() as conn:
        await conn.execute(text("UPDATE setup_tokens SET expires_at = now() - interval '1 s'"))
    expired = await client.post(
        "/api/v1/setup",
        json={
            "setup_token": token,
            "email": "a@example.com",
            "display_name": "A",
            "password": GOOD_PASSWORD,
        },
    )
    assert expired.status_code == 400

    assert (await _setup_admin(client, db)).status_code == 201
    reuse = await client.post(
        "/api/v1/setup",
        json={
            "setup_token": token,
            "email": "b@example.com",
            "display_name": "B",
            "password": GOOD_PASSWORD,
        },
    )
    assert reuse.status_code == 400


async def test_setup_rejects_weak_password(client: httpx2.AsyncClient, db: Database) -> None:
    token = await auth_service.issue_setup_token(db)
    response = await client.post(
        "/api/v1/setup",
        json={
            "setup_token": token,
            "email": "a@example.com",
            "display_name": "A",
            "password": "password1234",
        },
    )
    assert response.status_code == 400
    assert "too common" in response.json()["detail"]


async def test_unsafe_requests_need_our_origin(client: httpx2.AsyncClient) -> None:
    for origin in (None, "https://evil.example"):
        headers = {"origin": origin} if origin else {}
        client.headers.pop("origin", None)
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "a@example.com", "password": "x"},
            headers=headers,
        )
        assert response.status_code == 403
    client.headers["origin"] = ORIGIN


async def test_login_does_not_reveal_accounts(
    client: httpx2.AsyncClient, db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup_admin(client, db)
    client.cookies.clear()
    calls: list[str | None] = []
    real_verify = passwords.verify_password

    def counting_verify(stored: str | None, password: str) -> bool:
        calls.append(stored)
        return real_verify(stored, password)

    monkeypatch.setattr(passwords, "verify_password", counting_verify)

    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": GOOD_PASSWORD}
    )
    wrong = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "not the password at all"},
    )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert "set-cookie" not in unknown.headers
    assert "set-cookie" not in wrong.headers
    assert len(calls) == 2  # a hash was verified both times (timing parity)


async def test_login_session_logout(client: httpx2.AsyncClient, db: Database) -> None:
    await _setup_admin(client, db)
    client.cookies.clear()
    assert (await client.get("/api/v1/auth/session")).status_code == 401

    login = await client.post(
        "/api/v1/auth/login", json={"email": " ADMIN@example.com ", "password": GOOD_PASSWORD}
    )
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]

    session = await client.get("/api/v1/auth/session")
    assert session.status_code == 200
    assert session.json()["csrf_token"] == csrf

    assert (await client.post("/api/v1/auth/logout")).status_code == 403  # no CSRF token
    assert (
        await client.post("/api/v1/auth/logout", headers={"x-csrf-token": "0" * 64})
    ).status_code == 403
    assert (
        await client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf})
    ).status_code == 204
    # The old cookie value no longer works even if replayed.
    client.cookies.set(COOKIE, login.cookies[COOKIE])
    assert (await client.get("/api/v1/auth/session")).status_code == 401


async def test_new_login_replaces_existing_session(
    client: httpx2.AsyncClient, db: Database
) -> None:
    first = await _setup_admin(client, db)
    old_token = first.cookies[COOKIE]

    await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": GOOD_PASSWORD}
    )

    assert client.cookies[COOKIE] != old_token
    assert await auth_service.authenticate(db, old_token) is None


async def test_password_change_needs_step_up_and_signs_out_others(
    client: httpx2.AsyncClient, db: Database
) -> None:
    from tests.db.test_mfa import enroll_totp

    setup = await _setup_admin(client, db)
    csrf = setup.json()["csrf_token"]
    body = {"current_password": GOOD_PASSWORD, "new_password": "a completely different passphrase"}

    # Password-only session: second factor required first.
    assert (
        await client.post("/api/v1/auth/password", headers={"x-csrf-token": csrf}, json=body)
    ).status_code == 403
    await enroll_totp(client, csrf)
    other = await auth_service.login(
        db, email="admin@example.com", password=GOOD_PASSWORD, ip=None, user_agent=None
    )

    wrong = await client.post(
        "/api/v1/auth/password",
        headers={"x-csrf-token": csrf},
        json={"current_password": "nope", "new_password": "x" * 20},
    )
    assert wrong.status_code == 400

    ok = await client.post("/api/v1/auth/password", headers={"x-csrf-token": csrf}, json=body)
    assert ok.status_code == 204
    assert await auth_service.authenticate(db, other.token) is None
    assert (await client.get("/api/v1/auth/session")).status_code == 200

    client.cookies.clear()
    old = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": GOOD_PASSWORD}
    )
    new = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": body["new_password"]}
    )
    assert (old.status_code, new.status_code) == (401, 200)


async def test_users_cannot_make_themselves_admin_or_see_others(
    client: httpx2.AsyncClient, db: Database
) -> None:
    await _setup_admin(client, db)
    async with db.system_transaction() as conn:
        from app.db import auth as store

        user_id = await store.create_user(
            conn,
            email="user@example.com",
            display_name="U",
            password_hash=passwords.hash_password(GOOD_PASSWORD),
            is_admin=False,
        )

    with pytest.raises(DBAPIError, match="is_admin can only change"):
        async with db.user_transaction(user_id) as conn:
            await conn.execute(
                text("UPDATE users SET is_admin = true WHERE id = :id"), {"id": user_id}
            )

    async with db.user_transaction(user_id) as conn:
        visible: list[str] = list((await conn.execute(text("SELECT email FROM users"))).scalars())
    assert visible == ["user@example.com"]


async def test_sessions_are_stored_hashed(client: httpx2.AsyncClient, db: Database) -> None:
    response = await _setup_admin(client, db)
    token = response.cookies[COOKIE]
    async with db.system_transaction() as conn:
        rows: list[bytes] = list(
            (await conn.execute(text("SELECT token_hash FROM sessions"))).scalars()
        )
    assert rows
    assert all(token.encode() not in bytes(h) for h in rows)


async def test_unknown_session_token_is_rejected(db: Database) -> None:
    assert await auth_service.authenticate(db, "") is None
    assert await auth_service.authenticate(db, uuid.uuid4().hex) is None
    assert await auth_service.authenticate(db, "x" * 10_000) is None
