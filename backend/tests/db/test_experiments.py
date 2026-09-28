"""Experimental features: the admin turns them on and makes each available; people opt in."""

from typing import Any

import pytest

from app.services import experiments
from tests.db import team as setup
from tests.db.team import U

pytestmark = pytest.mark.db

team = setup.team

type Team = tuple[U, U, U, str, str]


def _req(u: U, method: str, path: str, **kw: Any) -> Any:
    u._cookie()
    return u.client.request(method, path, headers={**u.h, **kw.pop("headers", {})}, **kw)


def test_experiments_are_off_until_chosen_by_admin_and_person(
    team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, viewer, _, _, _ = team
    feature = experiments.Experiment("Talk to the assistant", "Ask about a project.", "Beta.")
    monkeypatch.setattr(experiments, "REGISTRY", {"assistant.chat": feature})

    # Off by default: nothing offered, the admin sees it unavailable.
    assert viewer.get("/api/v1/experiments").json() == {"enabled": False, "features": []}
    admin_view = admin.get("/api/v1/admin/experiments").json()
    assert admin_view["enabled"] is False
    assert admin_view["features"][0]["available"] is False
    assert (
        _req(
            viewer, "PUT", "/api/v1/experiments/assistant.chat", json={"opted_in": True}
        ).status_code
        == 404
    )

    # Only admins change it; unknown features are refused.
    assert (
        _req(viewer, "PUT", "/api/v1/admin/experiments", json={"enabled": True}).status_code == 404
    )
    bad = _req(
        admin,
        "PUT",
        "/api/v1/admin/experiments",
        json={"enabled": True, "available": {"nope": True}},
    )
    assert bad.status_code == 422

    # The admin turns them on and makes the feature available; people then opt in themselves.
    r = _req(
        admin,
        "PUT",
        "/api/v1/admin/experiments",
        json={"enabled": True, "available": {"assistant.chat": True}},
    )
    assert r.status_code == 200, r.text
    offered = viewer.get("/api/v1/experiments").json()
    assert offered["features"][0]["name"] == "assistant.chat"
    assert offered["features"][0]["opted_in"] is False
    r = _req(viewer, "PUT", "/api/v1/experiments/assistant.chat", json={"opted_in": True})
    assert r.status_code == 204
    assert viewer.get("/api/v1/experiments").json()["features"][0]["opted_in"] is True
    assert admin.get("/api/v1/experiments").json()["features"][0]["opted_in"] is False

    # The master switch off stops it for everyone.
    _req(admin, "PUT", "/api/v1/admin/experiments", json={"enabled": False})
    assert viewer.get("/api/v1/experiments").json() == {"enabled": False, "features": []}
