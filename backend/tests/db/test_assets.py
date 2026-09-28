"""Assets: shared like projects; projects link to assets you can see (ADR 0005)."""

import asyncio
from typing import Any

import pytest

from app.db import attachments as attachment_store
from app.db.database import Database
from tests.db import test_collab
from tests.db.conftest import _settings
from tests.db.test_collab import U
from tests.test_files import jpeg_with_gps

pytestmark = pytest.mark.db

team = test_collab.team  # the shared fixture: owner, viewer, stranger, project, note

type Team = tuple[U, U, U, str, str]
BOAT = {
    "name": "Sea Ray 240",
    "kind": "boat",
    "details": [
        {"label": "Hull ID", "value": "SERA1234B626"},
        {"label": "Engine", "value": "350 MAG"},
    ],
}


def _req(u: U, method: str, path: str, **kw: Any) -> Any:
    u._cookie()
    return u.client.request(method, path, headers={**u.h, **kw.pop("headers", {})}, **kw)


def test_assets_are_private_until_shared(team: Team) -> None:
    owner, viewer, stranger, _, _ = team
    r = owner.post("/api/v1/assets", headers=owner.h, json=BOAT)
    assert r.status_code == 201, r.text
    boat = r.json()
    assert boat["role"] == "owner"
    assert boat["details"][0] == {"label": "Hull ID", "value": "SERA1234B626"}
    aid = boat["id"]

    assert viewer.get(f"/api/v1/assets/{aid}").status_code == 404
    assert viewer.get("/api/v1/assets").json() == []

    r = owner.post(
        f"/api/v1/assets/{aid}/members",
        headers=owner.h,
        json={"user_id": viewer.id, "role": "viewer"},
    )
    assert r.status_code == 201, r.text
    assert viewer.get(f"/api/v1/assets/{aid}").json()["role"] == "viewer"
    assert [a["id"] for a in viewer.get("/api/v1/assets").json()] == [aid]
    r = _req(viewer, "PUT", f"/api/v1/assets/{aid}", json=BOAT, headers={"if-match": '"1"'})
    assert r.status_code == 403
    assert _req(viewer, "DELETE", f"/api/v1/assets/{aid}").status_code == 403
    assert _req(stranger, "DELETE", f"/api/v1/assets/{aid}").status_code == 404

    # The owner edits with optimistic concurrency.
    r = _req(
        owner,
        "PUT",
        f"/api/v1/assets/{aid}",
        json={**BOAT, "notes": "Winter at Dock B"},
        headers={"if-match": '"1"'},
    )
    assert r.status_code == 200, r.text
    r = _req(owner, "PUT", f"/api/v1/assets/{aid}", json=BOAT, headers={"if-match": '"1"'})
    assert r.status_code == 409

    # The last owner can't leave or be demoted; a viewer may leave.
    r = _req(owner, "PATCH", f"/api/v1/assets/{aid}/members/{owner.id}", json={"role": "editor"})
    assert r.status_code == 409
    assert _req(viewer, "DELETE", f"/api/v1/assets/{aid}/members/{viewer.id}").status_code == 204
    assert viewer.get(f"/api/v1/assets/{aid}").status_code == 404


def test_projects_link_to_visible_assets_only(team: Team) -> None:
    owner, viewer, stranger, pid, _ = team
    aid = owner.post("/api/v1/assets", headers=owner.h, json=BOAT).json()["id"]
    theirs = stranger.post(
        "/api/v1/assets", headers=stranger.h, json={"name": "Their car", "kind": "vehicle"}
    ).json()["id"]

    # Can't link to an asset you can't see, and viewers can't link at all.
    assert (
        _req(owner, "PUT", f"/api/v1/projects/{pid}/asset", json={"asset_id": theirs}).status_code
        == 404
    )
    assert (
        _req(viewer, "PUT", f"/api/v1/projects/{pid}/asset", json={"asset_id": aid}).status_code
        == 403
    )
    assert (
        _req(owner, "PUT", f"/api/v1/projects/{pid}/asset", json={"asset_id": aid}).status_code
        == 204
    )

    # The project shows the asset to those who can see the asset...
    p = owner.get(f"/api/v1/projects/{pid}").json()
    assert (p["asset_id"], p["asset_name"], p["asset_kind"]) == (aid, "Sea Ray 240", "boat")
    # ...and hides it from project members who can't.
    p = viewer.get(f"/api/v1/projects/{pid}").json()
    assert p["asset_id"] is None
    assert p["asset_name"] is None

    # The asset's service history lists the project.
    history = owner.get(f"/api/v1/assets/{aid}").json()["history"]
    assert [h["id"] for h in history] == [pid]
    assert owner.get(f"/api/v1/assets/{aid}").json()["projects"] == 1

    assert (
        _req(owner, "PUT", f"/api/v1/projects/{pid}/asset", json={"asset_id": None}).status_code
        == 204
    )
    assert owner.get(f"/api/v1/projects/{pid}").json()["asset_id"] is None


def test_deleting_an_asset_unlinks_it_from_view(team: Team) -> None:
    owner, _, _, pid, _ = team
    aid = owner.post("/api/v1/assets", headers=owner.h, json=BOAT).json()["id"]
    _req(owner, "PUT", f"/api/v1/projects/{pid}/asset", json={"asset_id": aid})
    assert _req(owner, "DELETE", f"/api/v1/assets/{aid}").status_code == 204
    assert owner.get(f"/api/v1/assets/{aid}").status_code == 404
    assert owner.get(f"/api/v1/projects/{pid}").json()["asset_id"] is None


def test_asset_photo(team: Team) -> None:
    owner, viewer, stranger, _, _ = team
    aid = owner.post("/api/v1/assets", headers=owner.h, json=BOAT).json()["id"]
    owner._cookie()
    r = owner.client.put(
        f"/api/v1/assets/{aid}/photo",
        headers={**owner.h, "content-type": "application/octet-stream"},
        content=jpeg_with_gps(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["has_photo"] is True
    owner.post(
        f"/api/v1/assets/{aid}/members",
        headers=owner.h,
        json={"user_id": viewer.id, "role": "viewer"},
    )
    photo = viewer.get(f"/api/v1/assets/{aid}/photo")
    assert photo.status_code == 200
    assert b"Exif" not in photo.content  # location removed
    assert "sandbox" in photo.headers["content-security-policy"]
    assert (
        viewer.get(f"/api/v1/assets/{aid}/photo/thumbnail").headers["content-type"] == "image/webp"
    )
    assert stranger.get(f"/api/v1/assets/{aid}/photo").status_code == 404
    viewer._cookie()
    r = viewer.client.put(f"/api/v1/assets/{aid}/photo", headers=viewer.h, content=jpeg_with_gps())
    assert r.status_code == 403
    owner._cookie()
    r = owner.client.put(f"/api/v1/assets/{aid}/photo", headers=owner.h, content=b"%PDF-1.7\n")
    assert r.status_code == 415

    # The blob purge keeps files an asset uses.
    async def referenced() -> set[str]:
        db = Database(_settings())
        try:
            async with db.system_transaction() as conn:
                return await attachment_store.referenced_blobs(conn)
        finally:
            await db.dispose()

    assert len(asyncio.run(referenced())) >= 2
    assert _req(owner, "DELETE", f"/api/v1/assets/{aid}/photo").status_code == 204
    assert owner.get(f"/api/v1/assets/{aid}/photo").status_code == 404
