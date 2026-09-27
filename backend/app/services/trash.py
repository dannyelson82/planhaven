"""Trash: restore deleted things for 30 days; after that a system job removes them for good.

Who may restore mirrors who may delete: projects and assets by their owners; tasks, lists,
notes and files by the project's owners and editors (while the project itself exists).
"""

import uuid
from typing import Literal

from app import authz
from app.db import assets as asset_store
from app.db import auth as audit
from app.db import projects as project_store
from app.db import trash as store
from app.db.database import Database
from app.services import live
from app.services.auth import CurrentSession

Kind = Literal["project", "task", "list", "note", "attachment", "asset"]
TrashRow = store.TrashRow

_LIVE_KIND = {"task": "tasks", "list": "lists", "note": "notes", "attachment": "attachments"}


async def list_trash(db: Database, session: CurrentSession) -> list[TrashRow]:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        return await store.trash(conn)


async def restore(
    db: Database, session: CurrentSession, kind: Kind, item_id: uuid.UUID, ip: str | None
) -> None:
    project_id: uuid.UUID | None = None
    async with db.user_transaction(session.user.id) as conn:
        if kind == "project":
            access = authz.ProjectAccess(await project_store.role(conn, item_id))
            authz.require(session.principal, authz.Action.PROJECT_MANAGE, access)
            project_id = item_id
        elif kind == "asset":
            access = authz.ProjectAccess(await asset_store.role(conn, item_id))
            authz.require(session.principal, authz.Action.ASSET_MANAGE, access)
        else:
            project_id = await store.parent_project(conn, kind, item_id)
            if project_id is None or await store.project_deleted(conn, project_id):
                raise authz.NotFoundError("Not found.")
            access = authz.ProjectAccess(await project_store.role(conn, project_id))
            authz.require(session.principal, authz.Action.PROJECT_VIEW, access)
            authz.require(session.principal, authz.Action.PROJECT_EDIT, access)
        if not await store.restore(conn, kind, item_id):
            raise authz.NotFoundError("Not found.")
        await audit.record_audit(
            conn,
            action=f"{kind}.restored",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=project_id,
            resource_type=kind,
            resource_id=item_id,
        )
    if project_id is not None:
        live.publish(project_id, _LIVE_KIND.get(kind, "project"))


async def purge(db: Database) -> int:
    """Maintenance job: remove what has been in the trash for more than 30 days."""
    async with db.system_transaction() as conn:
        return await store.purge(conn)
