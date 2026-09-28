"""Trash: restore within 30 days by the right people; purge after (phase 0.2, M6)."""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.db.database import Database
from app.services import trash as trash_service
from tests.db import team as setup
from tests.db.conftest import _settings
from tests.db.team import U

pytestmark = pytest.mark.db

team = setup.team  # the shared fixture: owner, viewer, stranger, project, note

type Team = tuple[U, U, U, str, str]


def _req(u: U, method: str, path: str, **kw: Any) -> Any:
    u._cookie()
    return u.client.request(method, path, headers={**u.h, **kw.pop("headers", {})}, **kw)


def test_restore_rules(team: Team) -> None:
    owner, viewer, stranger, pid, nid = team
    tid = owner.post(
        f"/api/v1/projects/{pid}/tasks", headers=owner.h, json={"title": "Sand hull"}
    ).json()["id"]
    assert _req(owner, "DELETE", f"/api/v1/tasks/{tid}").status_code == 204
    assert _req(owner, "DELETE", f"/api/v1/notes/{nid}").status_code == 204

    items = {(i["kind"], i["id"]) for i in owner.get("/api/v1/trash").json()}
    assert {("task", tid), ("note", nid)} <= items
    assert viewer.get("/api/v1/trash").json() == []  # viewers can't restore, so see nothing

    assert _req(viewer, "POST", f"/api/v1/trash/task/{tid}/restore").status_code == 403
    assert _req(stranger, "POST", f"/api/v1/trash/task/{tid}/restore").status_code == 404
    assert _req(owner, "POST", f"/api/v1/trash/task/{tid}/restore").status_code == 204
    assert (
        _req(owner, "POST", f"/api/v1/trash/task/{tid}/restore").status_code == 404
    )  # not deleted
    titles = [t["title"] for t in owner.get(f"/api/v1/projects/{pid}/tasks").json()]
    assert "Sand hull" in titles
    assert _req(owner, "POST", f"/api/v1/trash/note/{nid}/restore").status_code == 204
    assert owner.get(f"/api/v1/notes/{nid}").status_code == 200


def test_projects_and_assets_restore_by_owner(team: Team) -> None:
    owner, viewer, _, pid, _ = team
    assert _req(owner, "DELETE", f"/api/v1/projects/{pid}").status_code == 204
    assert owner.get(f"/api/v1/projects/{pid}").status_code == 404
    assert ("project", pid) in {(i["kind"], i["id"]) for i in owner.get("/api/v1/trash").json()}
    assert _req(viewer, "POST", f"/api/v1/trash/project/{pid}/restore").status_code == 403
    assert _req(owner, "POST", f"/api/v1/trash/project/{pid}/restore").status_code == 204
    assert owner.get(f"/api/v1/projects/{pid}").status_code == 200

    aid = owner.post(
        "/api/v1/assets", headers=owner.h, json={"name": "Truck", "kind": "vehicle"}
    ).json()["id"]
    assert _req(owner, "DELETE", f"/api/v1/assets/{aid}").status_code == 204
    assert _req(owner, "POST", f"/api/v1/trash/asset/{aid}/restore").status_code == 204
    assert owner.get(f"/api/v1/assets/{aid}").status_code == 200
    assert _req(owner, "POST", f"/api/v1/trash/bogus/{aid}/restore").status_code == 422


async def _age_and_purge(owner_id: str, pid: str) -> tuple[int, int]:
    db = Database(_settings())
    try:
        # The project's owner may set deleted_at (the system context may only purge).
        async with db.user_transaction(uuid.UUID(owner_id)) as conn:
            await conn.execute(
                text("UPDATE projects SET deleted_at = now() - interval '31 days' WHERE id = :p"),
                {"p": pid},
            )
        purged = await trash_service.purge(db)
        async with db.system_transaction() as conn:
            left = await conn.scalar(
                text("SELECT count(*) FROM projects WHERE id = :p"), {"p": pid}
            )
        return purged, int(left or 0)
    finally:
        await db.dispose()


def test_purge_after_30_days(team: Team) -> None:
    owner, _, _, pid, _ = team
    assert _req(owner, "DELETE", f"/api/v1/projects/{pid}").status_code == 204
    purged, left = asyncio.run(_age_and_purge(owner.id, pid))
    assert purged >= 1
    assert left == 0
    assert all(i["id"] != pid for i in owner.get("/api/v1/trash").json())


async def _user_purge(user_id: str) -> None:
    db = Database(_settings())
    try:
        async with db.user_transaction(uuid.UUID(user_id)) as conn:
            await conn.execute(text("SELECT app.purge_trash()"))
    finally:
        await db.dispose()


def test_only_the_system_can_purge(team: Team) -> None:
    owner, _, _, _, _ = team
    with pytest.raises(Exception, match="system job"):
        asyncio.run(_user_purge(owner.id))
