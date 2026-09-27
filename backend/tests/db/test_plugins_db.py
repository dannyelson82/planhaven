"""Plugin context permissions and RLS on plugin data; admin plugin endpoints."""

import uuid

import pytest
from planhaven_sdk import Event, Manifest, PluginError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.database import Database
from app.plugins_host.host import HostPluginContext, discover, load
from tests.db.test_projects import User, _project, _share
from tests.test_plugins import FIXTURES

pytestmark = [pytest.mark.db, pytest.mark.anyio]


def _manifest(**permissions: object) -> Manifest:
    return Manifest.model_validate(
        {
            "plugin": {"id": "example", "name": "E", "version": "1", "api_version": "1"},
            "permissions": permissions,
        }
    )


async def test_context_acts_as_the_user_under_rls(people: dict[str, User], db: Database) -> None:
    owner, viewer, stranger = people["owner"], people["viewer"], people["stranger"]
    pid = uuid.UUID(str((await _project(owner))["id"]))
    await _share(db, owner, str(pid), viewer, "viewer")
    manifest = _manifest(project_data=["read", "write"], projects=["read"])

    as_owner = HostPluginContext(db, manifest, owner.id)
    await as_owner.put_data("project", pid, "layout", {"sheets": 3})
    assert await as_owner.get_data("project", pid, "layout") == {"sheets": 3}
    assert (await as_owner.get_project(pid)).role == "owner"  # type: ignore[union-attr]

    as_viewer = HostPluginContext(db, manifest, viewer.id)
    assert await as_viewer.get_data("project", pid, "layout") == {"sheets": 3}
    with pytest.raises(DBAPIError, match="row-level security"):
        await as_viewer.put_data("project", pid, "layout", {"sheets": 0})

    as_stranger = HostPluginContext(db, manifest, stranger.id)
    assert await as_stranger.get_data("project", pid, "layout") is None
    assert await as_stranger.get_project(pid) is None


async def test_manifest_permissions_are_enforced(people: dict[str, User], db: Database) -> None:
    owner = people["owner"]
    pid = uuid.UUID(str((await _project(owner))["id"]))
    read_only = HostPluginContext(db, _manifest(project_data=["read"]), owner.id)
    with pytest.raises(PluginError, match="project_data:write"):
        await read_only.put_data("project", pid, "k", 1)
    with pytest.raises(PluginError, match="projects:read"):
        await read_only.get_project(pid)
    with pytest.raises(PluginError, match="user_data:read"):
        await read_only.get_data("user", owner.id, "k")
    writer = HostPluginContext(db, _manifest(project_data=["write"]), owner.id)
    with pytest.raises(PluginError, match="too large"):
        await writer.put_data("project", pid, "big", "x" * 70_000)


async def test_example_plugin_handler_runs_with_its_context(
    people: dict[str, User], db: Database
) -> None:
    owner = people["owner"]
    pid = uuid.UUID(str((await _project(owner))["id"]))
    loaded = load(discover((FIXTURES,)), {"example"})
    ctx = HostPluginContext(db, loaded.manifests["example"], owner.id)
    for _, handler in loaded.handlers["task.completed"]:
        await handler(ctx, Event(type="task.completed", project_id=pid))
        await handler(ctx, Event(type="task.completed", project_id=pid))
    assert await ctx.get_data("project", pid, "completed") == 2


async def test_admin_plugin_endpoints(people: dict[str, User], db: Database) -> None:
    owner = people["owner"]
    listed = {p["id"]: p for p in (await owner.client.get("/api/v1/admin/plugins")).json()}
    assert listed["example"]["compatible"] is True
    assert listed["example"]["enabled"] is False
    assert listed["wrong_api"]["error"] == "unsupported api_version"

    ok = await owner.client.post(
        "/api/v1/admin/plugins/example/enabled", headers=owner.h, json={"value": True}
    )
    assert ok.json() == {"restart_required": True}
    refused = await owner.client.post(
        "/api/v1/admin/plugins/wrong_api/enabled", headers=owner.h, json={"value": True}
    )
    assert refused.status_code == 400
    missing = await owner.client.post(
        "/api/v1/admin/plugins/nothere/enabled", headers=owner.h, json={"value": True}
    )
    assert missing.status_code == 404
    listed = {p["id"]: p for p in (await owner.client.get("/api/v1/admin/plugins")).json()}
    assert listed["example"]["enabled"] is True
    async with db.system_transaction() as conn:
        await conn.execute(text("UPDATE plugin_states SET enabled = false"))
