"""Items a task needs, picked from its project's lists (owner request, 2026-09-28)."""

import uuid
from typing import Any

from app import authz
from app.db import projects as project_store
from app.db import task_needs as store
from app.db.database import Database
from app.services import live
from app.services.auth import CurrentSession

NeedRow = store.NeedRow
MAX_NEEDS = 100


class NeedsError(Exception):
    """Items that aren't on this project's lists (message is safe to show)."""


async def _access(conn: Any, project_id: uuid.UUID) -> authz.ProjectAccess:
    access = authz.ProjectAccess(await project_store.role(conn, project_id))
    if access.role is not None and await project_store.get_project(conn, project_id) is None:
        return authz.ProjectAccess(None)
    return access


async def needs_for_project(
    db: Database, session: CurrentSession, project_id: uuid.UUID
) -> list[NeedRow]:
    async with db.user_transaction(session.user.id) as conn:
        authz.require(session.principal, authz.Action.PROJECT_VIEW, await _access(conn, project_id))
        return await store.needs_for_project(conn, project_id)


async def set_needs(
    db: Database, session: CurrentSession, task_id: uuid.UUID, item_ids: list[uuid.UUID]
) -> None:
    item_ids = list(dict.fromkeys(item_ids))  # keep order, drop repeats
    async with db.user_transaction(session.user.id) as conn:
        task = await project_store.get_task(conn, task_id)
        if task is None:
            raise authz.NotFoundError("Not found.")
        access = await _access(conn, task.project_id)
        authz.require(session.principal, authz.Action.PROJECT_VIEW, access)
        authz.require(session.principal, authz.Action.PROJECT_EDIT, access)
        found = await store.items_in_project(conn, task.project_id, item_ids) if item_ids else set()
        if len(found) != len(item_ids):
            raise NeedsError("Some of those items aren't on this project's lists.")
        await store.set_needs(conn, task_id, task.project_id, item_ids)
    live.publish(task.project_id, "tasks")
