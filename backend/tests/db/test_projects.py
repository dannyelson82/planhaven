"""Projects and tasks: roles, isolation, concurrency, pagination and events
(ARCHITECTURE.md §7.5, §8.2, §8.3)."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.db.database import Database
from app.main import create_app
from tests.db.conftest import _settings
from tests.db.test_invites_admin import accept, admin_client, client_from, invite
from tests.db.test_mfa import enroll_totp

pytestmark = [pytest.mark.db, pytest.mark.anyio]


@dataclass
class User:
    client: httpx2.AsyncClient
    csrf: str
    id: uuid.UUID

    @property
    def h(self) -> dict[str, str]:
        return {"x-csrf-token": self.csrf}


@pytest.fixture
async def people(owner_db: Database, db: Database) -> AsyncIterator[dict[str, User]]:
    async with owner_db.anonymous_transaction() as conn:
        await conn.execute(text("TRUNCATE users, sessions, setup_tokens CASCADE"))
    app: FastAPI = create_app(_settings())
    c, headers, _ = await admin_client(app, db)
    me = uuid.UUID((await c.get("/api/v1/auth/session")).json()["user"]["id"])
    out = {"owner": User(c, headers["x-csrf-token"], me)}
    for n, name in enumerate(("editor", "viewer", "stranger"), start=40):
        token = await invite(c, headers)
        uc = client_from(app, f"198.51.100.{n}")
        joined = await accept(uc, token, f"{name}@example.com")
        csrf = joined.json()["csrf_token"]
        await enroll_totp(uc, csrf)
        out[name] = User(uc, csrf, uuid.UUID(joined.json()["user"]["id"]))
    yield out
    for u in out.values():
        await u.client.aclose()
    await app.state.db.dispose()


async def _share(db: Database, owner: User, project_id: str, user: User, role: str) -> None:
    async with db.user_transaction(owner.id) as conn:
        await conn.execute(
            text("INSERT INTO project_members (project_id, user_id, role) VALUES (:p, :u, :r)"),
            {"p": project_id, "u": user.id, "r": role},
        )


async def _project(owner: User, **fields: object) -> dict[str, object]:
    r = await owner.client.post(
        "/api/v1/projects", headers=owner.h, json={"title": "Fix roof", **fields}
    )
    assert r.status_code == 201, r.text
    body: dict[str, object] = r.json()
    return body


async def test_roles_control_what_members_can_do(people: dict[str, User], db: Database) -> None:
    owner, editor, viewer, stranger = (people[k] for k in ("owner", "editor", "viewer", "stranger"))
    project = await _project(owner, description="Shingles", stage="planning")
    pid = project["id"]
    assert project["role"] == "owner"
    await _share(db, owner, str(pid), editor, "editor")
    await _share(db, owner, str(pid), viewer, "viewer")

    # Everyone who's a member can see it; a stranger gets 404, not 403.
    for u in (owner, editor, viewer):
        assert (await u.client.get(f"/api/v1/projects/{pid}")).status_code == 200
    assert (await stranger.client.get(f"/api/v1/projects/{pid}")).status_code == 404
    assert (await stranger.client.get(f"/api/v1/projects/{pid}/tasks")).status_code == 404
    listed = (await stranger.client.get("/api/v1/projects")).json()["items"]
    assert pid not in [p["id"] for p in listed]

    # Editors change content; viewers can't; only owners manage and delete.
    v = (await editor.client.get(f"/api/v1/projects/{pid}")).json()["version"]
    ok = await editor.client.patch(
        f"/api/v1/projects/{pid}",
        headers={**editor.h, "if-match": f'"{v}"'},
        json={"stage": "ready"},
    )
    assert ok.status_code == 200
    v = ok.json()["version"]
    assert (
        await viewer.client.patch(
            f"/api/v1/projects/{pid}", headers={**viewer.h, "if-match": str(v)}, json={"title": "x"}
        )
    ).status_code == 403
    assert (
        await editor.client.patch(
            f"/api/v1/projects/{pid}",
            headers={**editor.h, "if-match": str(v)},
            json={"local_ai_only": True},
        )
    ).status_code == 403
    assert (
        await editor.client.delete(f"/api/v1/projects/{pid}", headers=editor.h)
    ).status_code == 403
    assert (
        await viewer.client.post(
            f"/api/v1/projects/{pid}/tasks", headers=viewer.h, json={"title": "x"}
        )
    ).status_code == 403
    assert (
        await stranger.client.post(
            f"/api/v1/projects/{pid}/tasks", headers=stranger.h, json={"title": "x"}
        )
    ).status_code == 404

    assert (
        await owner.client.delete(f"/api/v1/projects/{pid}", headers=owner.h)
    ).status_code == 204
    assert (await editor.client.get(f"/api/v1/projects/{pid}")).status_code == 404


async def test_database_enforces_roles_even_without_the_app(
    people: dict[str, User], db: Database
) -> None:
    owner, editor, viewer, stranger = (people[k] for k in ("owner", "editor", "viewer", "stranger"))
    pid = (await _project(owner))["id"]
    await _share(db, owner, str(pid), editor, "editor")
    await _share(db, owner, str(pid), viewer, "viewer")

    async with db.user_transaction(stranger.id) as conn:
        assert (
            await conn.scalar(text("SELECT count(*) FROM projects WHERE id = :p"), {"p": pid}) == 0
        )
    async with db.user_transaction(viewer.id) as conn:
        result = await conn.execute(
            text("UPDATE projects SET title = 'x' WHERE id = :p"), {"p": pid}
        )
        assert result.rowcount == 0  # RLS: the row isn't updatable for a viewer
    with pytest.raises(DBAPIError, match="only the project owner"):
        async with db.user_transaction(editor.id) as conn:
            await conn.execute(
                text("UPDATE projects SET local_ai_only = true WHERE id = :p"), {"p": pid}
            )
    with pytest.raises(DBAPIError, match="row-level security"):
        async with db.user_transaction(editor.id) as conn:  # editors can't share
            await conn.execute(
                text("INSERT INTO project_members VALUES (:p, :u, 'viewer')"),
                {"p": pid, "u": stranger.id},
            )
    with pytest.raises(DBAPIError, match="row-level security"):
        async with db.user_transaction(stranger.id) as conn:  # can't join by themselves
            await conn.execute(
                text("INSERT INTO project_members VALUES (:p, :u, 'owner')"),
                {"p": pid, "u": stranger.id},
            )
    with pytest.raises(ProgrammingError, match="permission denied"):
        async with db.user_transaction(owner.id) as conn:  # no hard deletes for the app
            await conn.execute(text("DELETE FROM projects WHERE id = :p"), {"p": pid})


async def test_assignee_sees_their_task_but_not_the_project(
    people: dict[str, User], db: Database
) -> None:
    owner, stranger = people["owner"], people["stranger"]
    pid = (await _project(owner))["id"]
    task = (
        await owner.client.post(
            f"/api/v1/projects/{pid}/tasks", headers=owner.h, json={"title": "Take out the trash"}
        )
    ).json()
    async with db.user_transaction(owner.id) as conn:
        await conn.execute(
            text("UPDATE tasks SET assignee_id = :u WHERE id = :t"),
            {"u": stranger.id, "t": task["id"]},
        )
    async with db.user_transaction(stranger.id) as conn:
        titles: list[str] = list(
            (await conn.execute(text("SELECT title FROM tasks"))).scalars().all()
        )
        projects = await conn.scalar(text("SELECT count(*) FROM projects"))
    assert list(titles) == ["Take out the trash"]
    assert projects == 0


async def test_tasks_crud_concurrency_and_events(people: dict[str, User], db: Database) -> None:
    owner = people["owner"]
    pid = (await _project(owner))["id"]
    created = await owner.client.post(
        f"/api/v1/projects/{pid}/tasks",
        headers=owner.h,
        json={"title": "Buy shingles", "due_at": "2026-10-03T00:00:00Z", "due_all_day": True},
    )
    assert created.status_code == 201
    task = created.json()
    assert created.headers["etag"] == f'"{task["version"]}"'

    missing = await owner.client.patch(
        f"/api/v1/tasks/{task['id']}", headers=owner.h, json={"done": True}
    )
    assert missing.status_code == 428
    done = await owner.client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers={**owner.h, "if-match": f'"{task["version"]}"'},
        json={"done": True, "due_at": None},
    )
    assert done.status_code == 200
    assert done.json()["done"] is True
    assert done.json()["due_at"] is None
    stale = await owner.client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers={**owner.h, "if-match": f'"{task["version"]}"'},
        json={"title": "Old view"},
    )
    assert stale.status_code == 409

    project = (await owner.client.get(f"/api/v1/projects/{pid}")).json()
    await owner.client.patch(
        f"/api/v1/projects/{pid}",
        headers={**owner.h, "if-match": str(project["version"])},
        json={"stage": "in_progress"},
    )
    async with db.system_transaction() as conn:
        types: set[str] = set(
            (
                await conn.execute(
                    text("SELECT type FROM events WHERE project_id = :p"), {"p": pid}
                )
            ).scalars()
        )
    assert {"task.completed", "project.stage_changed"} <= types

    assert (
        await owner.client.delete(f"/api/v1/tasks/{task['id']}", headers=owner.h)
    ).status_code == 204
    assert (await owner.client.get(f"/api/v1/projects/{pid}/tasks")).json() == []


async def test_pagination(people: dict[str, User]) -> None:
    owner = people["owner"]
    for i in range(5):
        await _project(owner, title=f"Project {i}")
    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": "2", **({"cursor": cursor} if cursor else {})}
        page = (await owner.client.get("/api/v1/projects", params=params)).json()
        seen += [p["title"] for p in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert sorted(seen) == [f"Project {i}" for i in range(5)]
    assert len(seen) == len(set(seen))
    assert (
        await owner.client.get("/api/v1/projects", params={"cursor": "garbage!"})
    ).status_code == 400
