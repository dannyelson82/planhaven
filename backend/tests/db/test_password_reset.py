"""Admin-made password reset links (SECURITY.md §7.1)."""

from typing import Any

import pytest

from tests.db import test_collab
from tests.db.test_collab import COOKIE, ORIGIN, PASSWORD, U

pytestmark = pytest.mark.db

team = test_collab.team  # the shared fixture: owner (admin), viewer, stranger, project, note

type Team = tuple[U, U, U, str, str]
NEW_PASSWORD = "a brand new passphrase 77"


def _public(u: U, path: str, body: dict[str, Any]) -> Any:
    u.client.cookies.clear()
    return u.client.post(path, json=body, headers={"origin": ORIGIN})


def test_reset_link(team: Team) -> None:
    owner, viewer, stranger, _, _ = team
    # Only admins; not for yourself.
    assert (
        stranger.post(
            f"/api/v1/admin/users/{viewer.id}/password-reset", headers=stranger.h
        ).status_code
        == 404
    )
    assert (
        owner.post(f"/api/v1/admin/users/{owner.id}/password-reset", headers=owner.h).status_code
        == 400
    )
    r = owner.post(f"/api/v1/admin/users/{viewer.id}/password-reset", headers=owner.h)
    assert r.status_code == 201, r.text
    url = r.json()["url"]
    assert "/reset#phv_rst_" in url
    token = url.split("#", 1)[1]

    assert _public(viewer, "/api/v1/password-reset/check", {"token": token}).json() == {
        "valid": True
    }
    # A weak password is refused and doesn't use up the link.
    weak = _public(viewer, "/api/v1/password-reset", {"token": token, "password": "password"})
    assert weak.status_code == 400
    ok = _public(viewer, "/api/v1/password-reset", {"token": token, "password": NEW_PASSWORD})
    assert ok.status_code == 204, ok.text
    # Used once only; every old session is signed out.
    again = _public(viewer, "/api/v1/password-reset", {"token": token, "password": NEW_PASSWORD})
    assert again.status_code == 400
    assert _public(viewer, "/api/v1/password-reset/check", {"token": token}).json() == {
        "valid": False
    }
    viewer.client.cookies.set(COOKIE, viewer.token)
    assert viewer.client.get("/api/v1/auth/session").status_code == 401

    # The new password works (the second factor is still required next).
    viewer.client.cookies.clear()
    login = viewer.client.post(
        "/api/v1/auth/login", json={"email": "viewer@example.com", "password": NEW_PASSWORD}
    )
    assert login.status_code == 200, login.text
    assert login.json()["mfa_verified"] is False
    old = viewer.client.post(
        "/api/v1/auth/login", json={"email": "viewer@example.com", "password": PASSWORD}
    )
    assert old.status_code in (400, 401)


def test_a_new_link_cancels_the_old_one(team: Team) -> None:
    owner, viewer, _, _, _ = team
    first = owner.post(f"/api/v1/admin/users/{viewer.id}/password-reset", headers=owner.h).json()
    owner.post(f"/api/v1/admin/users/{viewer.id}/password-reset", headers=owner.h)
    token = first["url"].split("#", 1)[1]
    assert _public(viewer, "/api/v1/password-reset/check", {"token": token}).json() == {
        "valid": False
    }
