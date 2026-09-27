"""Brute-force protection and the security log (SECURITY.md §7.11, §7.12)."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.core import security_log
from app.db import rate_limits
from app.db.database import Database
from app.main import create_app
from tests.db.conftest import _settings
from tests.db.test_auth import GOOD_PASSWORD, ORIGIN, _setup_admin

pytestmark = [pytest.mark.db, pytest.mark.anyio]


@pytest.fixture
async def app(owner_db: Database, tmp_path: Path) -> AsyncIterator[FastAPI]:
    async with owner_db.anonymous_transaction() as conn:
        await conn.execute(text("TRUNCATE users, sessions, setup_tokens, rate_limits CASCADE"))
    application = create_app(_settings())
    security_log.configure(str(tmp_path))
    yield application
    security_log.configure(None)
    await application.state.db.dispose()


def client_from(app: FastAPI, ip: str) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app, client=(ip, 40000)),
        base_url=ORIGIN,
        headers={"origin": ORIGIN},
    )


async def _login(
    c: httpx2.AsyncClient,
    password: str,
    email: str = "admin@example.com",
) -> httpx2.Response:
    c.cookies.clear()
    return await c.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_account_guessing_from_one_ip_is_blocked_but_not_elsewhere(
    app: FastAPI, db: Database
) -> None:
    async with (
        client_from(app, "198.51.100.10") as attacker,
        client_from(app, "203.0.113.20") as owner,
    ):
        await _setup_admin(owner, db)

        statuses = [
            (await _login(attacker, f"wrong guess {i:02d} xx")).status_code for i in range(6)
        ]
        assert statuses == [401] * 5 + [429]
        blocked = await _login(attacker, GOOD_PASSWORD)
        assert blocked.status_code == 429  # even the right password, from that IP
        assert int(blocked.headers["retry-after"]) > 0
        assert blocked.headers["content-type"] == "application/problem+json"

        # The real owner, elsewhere, isn't locked out by the attacker.
        assert (await _login(owner, GOOD_PASSWORD)).status_code == 200


async def test_many_accounts_from_one_ip_are_throttled(app: FastAPI) -> None:
    async with client_from(app, "198.51.100.11") as stuffer:
        codes = [
            (await _login(stuffer, "leaked password 1234", f"user{i}@example.com")).status_code
            for i in range(21)
        ]
    assert codes[:20] == [401] * 20
    assert codes[20] == 429


async def test_success_resets_the_account_bucket(app: FastAPI, db: Database) -> None:
    async with client_from(app, "198.51.100.12") as c:
        await _setup_admin(c, db)
        for _ in range(4):
            assert (await _login(c, "not my password at all")).status_code == 401
        assert (await _login(c, GOOD_PASSWORD)).status_code == 200
        for _ in range(4):
            assert (await _login(c, "not my password at all")).status_code == 401


async def test_second_factor_attempts_are_limited_per_user(app: FastAPI, db: Database) -> None:
    from tests.db.test_mfa import enroll_totp

    async with client_from(app, "198.51.100.13") as c:
        csrf = (await _setup_admin(c, db)).json()["csrf_token"]
        await enroll_totp(c, csrf)
        results = []
        for _ in range(3):  # new sessions dodge the 5-per-session rule, not the user limit
            csrf = (await _login(c, GOOD_PASSWORD)).json()["csrf_token"]
            for _ in range(4):
                r = await c.post(
                    "/api/v1/auth/mfa/totp/verify",
                    headers={"x-csrf-token": csrf},
                    json={"code": "000000"},
                )
                results.append(r.status_code)
    assert 429 in results
    assert results.index(429) == 10  # capacity 10 per user


async def test_setup_attempts_are_limited(app: FastAPI) -> None:
    async with client_from(app, "198.51.100.14") as c:
        codes = []
        for _ in range(6):
            r = await c.post(
                "/api/v1/setup",
                json={
                    "setup_token": "phv_setup_guess",
                    "email": "a@example.com",
                    "display_name": "A",
                    "password": GOOD_PASSWORD,
                },
            )
            codes.append(r.status_code)
    assert codes == [400] * 5 + [429]


async def test_buckets_are_atomic_under_concurrency(db: Database) -> None:
    async def take() -> float:
        async with db.system_transaction() as conn:
            return await rate_limits.take(conn, "test:concurrent", capacity=5, per_second=0.001)

    waits = await asyncio.gather(*(take() for _ in range(20)))
    assert sum(1 for w in waits if w == 0) == 5


async def test_security_log_format(app: FastAPI, db: Database, tmp_path: Path) -> None:
    async with client_from(app, "198.51.100.15") as c:
        await _setup_admin(c, db)
        await _login(c, "wrong password here")
        await _login(c, GOOD_PASSWORD)

    lines = [json.loads(line) for line in (tmp_path / "security.log").read_text().splitlines()]
    events = [(e["event"], e["ip"]) for e in lines]
    assert ("setup_completed", "198.51.100.15") in events
    assert ("login_failed", "198.51.100.15") in events
    assert ("login_succeeded", "198.51.100.15") in events
    raw = (tmp_path / "security.log").read_text()
    assert "admin@example.com" not in raw
    assert GOOD_PASSWORD not in raw
    assert "wrong password" not in raw
    for e in lines:
        assert set(e) >= {"ts", "event", "ip", "user_id"}
