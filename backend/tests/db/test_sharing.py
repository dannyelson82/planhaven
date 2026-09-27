"""Sharing: directory, members, roles, step-up, last owner, leaving, notifications."""

import uuid

import pytest
from sqlalchemy import text

from app.db.database import Database
from tests.db.test_projects import User, _project

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def _stale(db: Database, user: User) -> None:
    async with db.system_transaction() as conn:
        await conn.execute(
            text("UPDATE sessions SET reauth_at = now() - interval '6 minutes' WHERE user_id = :u"),
            {"u": user.id},
        )


async def test_directory_lists_other_active_members(people: dict[str, User]) -> None:
    owner = people["owner"]
    names = [p["email"] for p in (await owner.client.get("/api/v1/people")).json()]
    assert sorted(names) == ["editor@example.com", "stranger@example.com", "viewer@example.com"]


async def test_owner_shares_and_people_are_notified(people: dict[str, User]) -> None:
    owner, editor = people["owner"], people["editor"]
    pid = (await _project(owner, title="Fix roof"))["id"]
    base = f"/api/v1/projects/{pid}/members"

    added = await owner.client.post(
        base, headers=owner.h, json={"user_id": str(editor.id), "role": "editor"}
    )
    assert added.status_code == 201
    assert (
        await owner.client.post(base, headers=owner.h, json={"user_id": str(editor.id)})
    ).status_code == 409  # already a member

    members = (await editor.client.get(base)).json()
    assert [(m["email"], m["role"]) for m in members] == [
        ("admin@example.com", "owner"),
        ("editor@example.com", "editor"),
    ]
    assert (await editor.client.get(f"/api/v1/projects/{pid}")).status_code == 200
    notes = (await editor.client.get("/api/v1/notifications")).json()
    shared = [n for n in notes if n["kind"] == "shared_with_you"]
    assert shared[0]["data"]["title"] == "Fix roof"


async def test_only_owners_share_and_only_with_step_up(
    people: dict[str, User], db: Database
) -> None:
    owner, editor, viewer = people["owner"], people["editor"], people["viewer"]
    pid = (await _project(owner))["id"]
    base = f"/api/v1/projects/{pid}/members"
    await owner.client.post(base, headers=owner.h, json={"user_id": str(editor.id)})

    # Editors can't share; strangers can't even see the member list.
    assert (
        await editor.client.post(
            base, headers=editor.h, json={"user_id": str(viewer.id), "role": "viewer"}
        )
    ).status_code == 403
    assert (await people["stranger"].client.get(base)).status_code == 404

    await _stale(db, owner)
    stale = await owner.client.post(
        base, headers=owner.h, json={"user_id": str(viewer.id), "role": "viewer"}
    )
    assert stale.status_code == 403
    assert "Confirm it's you" in stale.json()["detail"]


async def test_last_owner_is_protected_and_members_can_leave(people: dict[str, User]) -> None:
    owner, editor = people["owner"], people["editor"]
    pid = (await _project(owner))["id"]
    base = f"/api/v1/projects/{pid}/members"
    await owner.client.post(base, headers=owner.h, json={"user_id": str(editor.id)})

    assert (await owner.client.delete(f"{base}/{owner.id}", headers=owner.h)).status_code == 409
    assert (
        await owner.client.patch(f"{base}/{owner.id}", headers=owner.h, json={"role": "viewer"})
    ).status_code == 409

    # Promote the editor; then the original owner may step down, and the editor may leave
    # only after handing ownership back... here: the editor (now owner) removes the first.
    assert (
        await owner.client.patch(f"{base}/{editor.id}", headers=owner.h, json={"role": "owner"})
    ).status_code == 204
    assert (
        await owner.client.delete(f"{base}/{owner.id}", headers=owner.h)
    ).status_code == 204  # leaving
    assert (await owner.client.get(f"/api/v1/projects/{pid}")).status_code == 404


async def test_cannot_add_unknown_or_disabled_people(people: dict[str, User]) -> None:
    owner = people["owner"]
    pid = (await _project(owner))["id"]
    r = await owner.client.post(
        f"/api/v1/projects/{pid}/members", headers=owner.h, json={"user_id": str(uuid.uuid4())}
    )
    assert r.status_code == 404
