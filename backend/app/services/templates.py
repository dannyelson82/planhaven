"""Templates: a list, or a project's tasks, saved to reuse in later projects (owner request,
2026-09-28).

A template is private to its creator until they share it, one person at a time (like
contacts: owner, editor, viewer). Using one copies it into a project the person can edit: a
list template becomes a new list with its items (quantities and estimated prices); a task
template adds its tasks. The template doesn't change, and later changes to it don't reach
what was made from it.
"""

import uuid
from typing import Any, Literal

from app import authz
from app.db import auth as audit
from app.db import lists as list_store
from app.db import projects as project_store
from app.db import templates as store
from app.db.database import Database
from app.services import live
from app.services.auth import CurrentSession
from app.services.projects import ConflictError

TemplateRow = store.TemplateRow
TemplateItemRow = store.TemplateItemRow
Kind = Literal["list", "tasks"]

MAX_ITEMS = 500


class EmptyTemplateError(Exception):
    """Nothing to save (message is safe to show)."""


async def _template_access(
    conn: Any, template_id: uuid.UUID
) -> tuple[TemplateRow, authz.ProjectAccess]:
    template = await store.get_template(conn, template_id)
    if template is None:
        raise authz.NotFoundError("Not found.")
    return template, authz.ProjectAccess(template.role)


async def _project_access(conn: Any, project_id: uuid.UUID) -> authz.ProjectAccess:
    access = authz.ProjectAccess(await project_store.role(conn, project_id))
    if access.role is not None and await project_store.get_project(conn, project_id) is None:
        return authz.ProjectAccess(None)
    return access


def _audit(
    action: str, session: CurrentSession, template_id: uuid.UUID, ip: str | None
) -> dict[str, Any]:
    return {
        "action": action,
        "actor_user_id": session.user.id,
        "ip": ip,
        "resource_type": "template",
        "resource_id": template_id,
    }


async def list_templates(
    db: Database, session: CurrentSession, kind: Kind | None = None
) -> list[TemplateRow]:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        rows = await store.list_templates(conn)
    return [t for t in rows if t.role is not None and (kind is None or t.kind == kind)]


async def get_template(
    db: Database, session: CurrentSession, template_id: uuid.UUID
) -> tuple[TemplateRow, list[TemplateItemRow]]:
    async with db.user_transaction(session.user.id) as conn:
        template, access = await _template_access(conn, template_id)
        authz.require(session.principal, authz.Action.TEMPLATE_VIEW, access)
        return template, await store.items(conn, template_id)


async def _create(
    conn: Any,
    session: CurrentSession,
    *,
    kind: Kind,
    list_kind: str | None,
    name: str,
    entries: list[dict[str, Any]],
    ip: str | None,
) -> TemplateRow:
    if not entries:
        raise EmptyTemplateError("There's nothing to save in this template yet.")
    template_id = await store.create_template(
        conn,
        user_id=session.user.id,
        kind=kind,
        list_kind=list_kind,
        name=name,
        entries=entries[:MAX_ITEMS],
    )
    await audit.record_audit(conn, **_audit("template.created", session, template_id, ip))
    template = await store.get_template(conn, template_id)
    if template is None:
        raise RuntimeError("created template not visible")
    return template


async def save_list(
    db: Database, session: CurrentSession, list_id: uuid.UUID, name: str, ip: str | None
) -> TemplateRow:
    """A template from a list: all its items, with quantities, units and estimated prices."""
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        row = await list_store.get_list(conn, list_id)
        if row is None:
            raise authz.NotFoundError("Not found.")
        authz.require(
            session.principal,
            authz.Action.PROJECT_VIEW,
            await _project_access(conn, row.project_id),
        )
        entries = [
            {
                "text": i.text,
                "quantity": i.quantity,
                "unit": i.unit,
                "price_cents": i.price_cents,
                "notes": "",
            }
            for i in await list_store.items(conn, list_id)
        ]
        return await _create(
            conn,
            session,
            kind="list",
            list_kind=row.kind,
            name=name,
            entries=entries,
            ip=ip,
        )


async def save_tasks(
    db: Database, session: CurrentSession, project_id: uuid.UUID, name: str, ip: str | None
) -> TemplateRow:
    """A template from a project's open tasks (titles and notes), in their order."""
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        authz.require(
            session.principal, authz.Action.PROJECT_VIEW, await _project_access(conn, project_id)
        )
        entries = [
            {"text": t.title, "quantity": None, "unit": None, "price_cents": None, "notes": t.notes}
            for t in await project_store.list_tasks(conn, project_id)
            if t.done_at is None
        ]
        return await _create(
            conn, session, kind="tasks", list_kind=None, name=name, entries=entries, ip=ip
        )


async def apply(
    db: Database,
    session: CurrentSession,
    template_id: uuid.UUID,
    project_id: uuid.UUID,
    ip: str | None,
) -> uuid.UUID | None:
    """Use a template in a project: a new list (returned), or its tasks added."""
    async with db.user_transaction(session.user.id) as conn:
        template, access = await _template_access(conn, template_id)
        authz.require(session.principal, authz.Action.TEMPLATE_VIEW, access)
        project = await _project_access(conn, project_id)
        authz.require(session.principal, authz.Action.PROJECT_VIEW, project)
        authz.require(session.principal, authz.Action.PROJECT_EDIT, project)
        entries = await store.items(conn, template_id)
        list_id = None
        if template.kind == "list":
            list_id = await list_store.create_list(
                conn,
                project_id=project_id,
                user_id=session.user.id,
                title=template.name,
                kind=template.list_kind or "shopping",
            )
            for entry in entries:
                await list_store.create_item(
                    conn,
                    item_id=uuid.uuid7(),
                    list_id=list_id,
                    project_id=project_id,
                    user_id=session.user.id,
                    text_=entry.text,
                    quantity=entry.quantity,
                    unit=entry.unit,
                    price_cents=entry.price_cents,
                )
        else:
            for entry in entries:
                await project_store.create_task(
                    conn,
                    project_id=project_id,
                    user_id=session.user.id,
                    title=entry.text[:300],
                    notes=entry.notes,
                    due_at=None,
                    due_all_day=False,
                )
        await audit.record_audit(
            conn, **_audit("template.used", session, template_id, ip), project_id=project_id
        )
    live.publish(project_id, "lists" if template.kind == "list" else "tasks")
    return list_id


async def rename(
    db: Database,
    session: CurrentSession,
    template_id: uuid.UUID,
    expected_version: int,
    name: str,
    ip: str | None,
) -> TemplateRow:
    async with db.user_transaction(session.user.id) as conn:
        _, access = await _template_access(conn, template_id)
        authz.require(session.principal, authz.Action.TEMPLATE_EDIT, access)
        if await store.rename(conn, template_id, expected_version, name) is None:
            raise ConflictError
        await audit.record_audit(conn, **_audit("template.renamed", session, template_id, ip))
        updated = await store.get_template(conn, template_id)
    if updated is None:
        raise authz.NotFoundError("Not found.")
    return updated


async def delete_item(db: Database, session: CurrentSession, item_id: uuid.UUID) -> None:
    async with db.user_transaction(session.user.id) as conn:
        item = await store.get_item(conn, item_id)
        if item is None:
            raise authz.NotFoundError("Not found.")
        _, access = await _template_access(conn, item.template_id)
        authz.require(session.principal, authz.Action.TEMPLATE_EDIT, access)
        await store.delete_item(conn, item_id)
        await store.touch(conn, item.template_id)


async def delete_template(
    db: Database, session: CurrentSession, template_id: uuid.UUID, ip: str | None
) -> None:
    async with db.user_transaction(session.user.id) as conn:
        _, access = await _template_access(conn, template_id)
        authz.require(session.principal, authz.Action.TEMPLATE_VIEW, access)
        authz.require(session.principal, authz.Action.TEMPLATE_MANAGE, access)
        await audit.record_audit(conn, **_audit("template.deleted", session, template_id, ip))
        await store.delete_template(conn, template_id)
