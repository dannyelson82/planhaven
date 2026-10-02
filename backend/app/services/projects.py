"""Projects and tasks (ARCHITECTURE.md §7). Every operation checks authorization through
`authz.require` with the caller's project role, then runs in a user transaction so RLS
enforces the same rules again (ADR 0004)."""

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app import authz
from app.db import auth as audit
from app.db import projects as store
from app.db.database import Database
from app.services import live, merge
from app.services.auth import CurrentSession

# Row types the API layer serialises (the API may not import app.db directly).
ProjectRow = store.ProjectRow
TaskRow = store.TaskRow

STAGES = ("idea", "planning", "ready", "in_progress", "done", "archived")
MAX_PAGE = 200


class ConflictError(Exception):
    """The item changed since the client read it (optimistic concurrency, A§8.2)."""


@dataclass(frozen=True, slots=True)
class Page:
    items: list[store.ProjectRow]
    next_cursor: str | None


def _cursor(row: store.ProjectRow) -> str:
    raw = json.dumps([row.updated_at.isoformat(), str(row.id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        ts, ident = json.loads(raw)
        return datetime.fromisoformat(ts), uuid.UUID(ident)
    except ValueError, TypeError:
        raise ValueError("invalid cursor") from None


async def _access(conn: Any, project_id: uuid.UUID) -> authz.ProjectAccess:
    return authz.ProjectAccess(await store.role(conn, project_id))


async def create_project(
    db: Database,
    session: CurrentSession,
    *,
    title: str,
    description: str,
    stage: str,
    ip: str | None,
) -> store.ProjectRow:
    principal = session.principal
    authz.require(principal, authz.Action.USE_APP)
    async with db.user_transaction(principal.user_id) as conn:
        project_id = await store.create_project(
            conn, user_id=principal.user_id, title=title, description=description, stage=stage
        )
        await audit.record_audit(
            conn,
            action="project.created",
            actor_user_id=principal.user_id,
            ip=ip,
            project_id=project_id,
            resource_type="project",
            resource_id=project_id,
        )
        row = await store.get_project(conn, project_id)
    if row is None:
        raise RuntimeError("created project not visible")
    return row


async def list_projects(
    db: Database, session: CurrentSession, *, stage: str | None, cursor: str | None, limit: int
) -> Page:
    principal = session.principal
    authz.require(principal, authz.Action.USE_APP)
    limit = max(1, min(limit, MAX_PAGE))
    async with db.user_transaction(principal.user_id) as conn:
        rows = await store.list_projects(
            conn, stage=stage, after=_decode_cursor(cursor), limit=limit + 1
        )
    more = len(rows) > limit
    rows = rows[:limit]
    return Page(rows, _cursor(rows[-1]) if more and rows else None)


async def get_project(
    db: Database, session: CurrentSession, project_id: uuid.UUID
) -> store.ProjectRow:
    principal = session.principal
    async with db.user_transaction(principal.user_id) as conn:
        authz.require(principal, authz.Action.PROJECT_VIEW, await _access(conn, project_id))
        row = await store.get_project(conn, project_id)
    if row is None:
        raise authz.NotFoundError("Not found.")
    return row


async def update_project(
    db: Database,
    session: CurrentSession,
    project_id: uuid.UUID,
    *,
    expected_version: int,
    title: str | None,
    description: str | None,
    stage: str | None,
    local_ai_only: bool | None,
    ip: str | None,
) -> store.ProjectRow:
    principal = session.principal
    async with db.user_transaction(principal.user_id) as conn:
        access = await _access(conn, project_id)
        authz.require(principal, authz.Action.PROJECT_VIEW, access)
        authz.require(principal, authz.Action.PROJECT_EDIT, access)
        if local_ai_only is not None:
            authz.require(principal, authz.Action.PROJECT_MANAGE, access)
        before = await store.get_project(conn, project_id)
        if before is None:
            raise authz.NotFoundError("Not found.")
        version = await store.update_project(
            conn,
            project_id,
            expected_version=expected_version,
            title=title,
            description=description,
            stage=stage,
            local_ai_only=local_ai_only,
        )
        if version is None:
            raise ConflictError("This project was changed elsewhere. Reload and try again.")
        if stage is not None and stage != before.stage:
            await store.emit(
                conn,
                "project.stage_changed",
                user_id=principal.user_id,
                project_id=project_id,
                payload={"from": before.stage, "to": stage},
            )
        await audit.record_audit(
            conn,
            action="project.updated",
            actor_user_id=principal.user_id,
            ip=ip,
            project_id=project_id,
            resource_type="project",
            resource_id=project_id,
        )
        after = await store.get_project(conn, project_id)
    if after is None:
        raise authz.NotFoundError("Not found.")
    live.publish(project_id, "project")
    return after


async def delete_project(
    db: Database, session: CurrentSession, project_id: uuid.UUID, ip: str | None
) -> None:
    principal = session.principal
    async with db.user_transaction(principal.user_id) as conn:
        access = await _access(conn, project_id)
        authz.require(principal, authz.Action.PROJECT_VIEW, access)
        authz.require(principal, authz.Action.PROJECT_MANAGE, access)
        await store.delete_project(conn, project_id)
        await audit.record_audit(
            conn,
            action="project.deleted",
            actor_user_id=principal.user_id,
            ip=ip,
            project_id=project_id,
            resource_type="project",
            resource_id=project_id,
        )
    live.publish(project_id, "project")


# ---------------------------------------------------------------- tasks


async def list_tasks(
    db: Database, session: CurrentSession, project_id: uuid.UUID
) -> list[store.TaskRow]:
    principal = session.principal
    async with db.user_transaction(principal.user_id) as conn:
        authz.require(principal, authz.Action.PROJECT_VIEW, await _access(conn, project_id))
        if await store.get_project(conn, project_id) is None:
            raise authz.NotFoundError("Not found.")
        return await store.list_tasks(conn, project_id)


async def create_task(
    db: Database,
    session: CurrentSession,
    project_id: uuid.UUID,
    *,
    title: str,
    notes: str,
    due_at: datetime | None,
    due_all_day: bool,
    ip: str | None,
) -> store.TaskRow:
    principal = session.principal
    async with db.user_transaction(principal.user_id) as conn:
        access = await _access(conn, project_id)
        authz.require(principal, authz.Action.PROJECT_VIEW, access)
        authz.require(principal, authz.Action.PROJECT_EDIT, access)
        if await store.get_project(conn, project_id) is None:
            raise authz.NotFoundError("Not found.")
        task_id = await store.create_task(
            conn,
            project_id=project_id,
            user_id=principal.user_id,
            title=title,
            notes=notes,
            due_at=due_at,
            due_all_day=due_all_day,
        )
        await audit.record_audit(
            conn,
            action="task.created",
            actor_user_id=principal.user_id,
            ip=ip,
            project_id=project_id,
            resource_type="task",
            resource_id=task_id,
        )
        row = await store.get_task(conn, task_id)
    if row is None:
        raise RuntimeError("created task not visible")
    live.publish(project_id, "tasks")
    return row


async def _task_access(conn: Any, task_id: uuid.UUID) -> tuple[store.TaskRow, authz.ProjectAccess]:
    task = await store.get_task(conn, task_id)
    if task is None:
        raise authz.NotFoundError("Not found.")
    return task, await _access(conn, task.project_id)


async def update_task(
    db: Database,
    session: CurrentSession,
    task_id: uuid.UUID,
    *,
    expected_version: int,
    title: str | None,
    notes: str | None,
    set_due: bool,
    due_at: datetime | None,
    due_all_day: bool | None,
    done: bool | None,
    ip: str | None,
    base: dict[str, Any] | None = None,
) -> store.TaskRow:
    """`base`: what the changed fields held when the client started (merge.unchanged_since)."""
    principal = session.principal
    async with db.user_transaction(principal.user_id) as conn:
        before, access = await _task_access(conn, task_id)
        authz.require(principal, authz.Action.PROJECT_VIEW, access)
        authz.require(principal, authz.Action.PROJECT_EDIT, access)
        changing = {
            name: value
            for name, value in {
                "title": title,
                "notes": notes,
                "due_all_day": due_all_day,
                "done": done,
            }.items()
            if value is not None
        } | ({"due_at": due_at} if set_due else {})
        current = {
            "title": before.title,
            "notes": before.notes,
            "due_at": before.due_at,
            "due_all_day": before.due_all_day,
            "done": before.done_at is not None,
        }
        expected = expected_version
        if expected != before.version and merge.unchanged_since(current, changing, base):
            expected = before.version  # only other fields changed meanwhile: keep both
        version = await store.update_task(
            conn,
            task_id,
            user_id=principal.user_id,
            expected_version=expected,
            title=title,
            notes=notes,
            set_due=set_due,
            due_at=due_at,
            due_all_day=due_all_day,
            done=done,
        )
        if version is None:
            raise ConflictError("This task was changed elsewhere. Reload and try again.")
        if done is True and before.done_at is None:
            await store.emit(
                conn,
                "task.completed",
                user_id=principal.user_id,
                project_id=before.project_id,
                payload={"task_id": str(task_id)},
            )
        await audit.record_audit(
            conn,
            action="task.updated",
            actor_user_id=principal.user_id,
            ip=ip,
            project_id=before.project_id,
            resource_type="task",
            resource_id=task_id,
        )
        after = await store.get_task(conn, task_id)
    if after is None:
        raise authz.NotFoundError("Not found.")
    live.publish(before.project_id, "tasks")
    return after


async def delete_task(
    db: Database, session: CurrentSession, task_id: uuid.UUID, ip: str | None
) -> None:
    principal = session.principal
    async with db.user_transaction(principal.user_id) as conn:
        task, access = await _task_access(conn, task_id)
        authz.require(principal, authz.Action.PROJECT_VIEW, access)
        authz.require(principal, authz.Action.PROJECT_EDIT, access)
        await store.delete_task(conn, task_id)
        await audit.record_audit(
            conn,
            action="task.deleted",
            actor_user_id=principal.user_id,
            ip=ip,
            project_id=task.project_id,
            resource_type="task",
            resource_id=task_id,
        )
    live.publish(task.project_id, "tasks")
