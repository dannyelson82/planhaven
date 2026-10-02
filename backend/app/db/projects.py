"""Queries for projects and tasks. Always called inside a user transaction, so RLS applies;
the service layer checks authorization first (defence in depth)."""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class ProjectRow:
    id: uuid.UUID
    title: str
    description: str
    stage: str
    local_ai_only: bool
    role: str | None
    created_at: datetime
    updated_at: datetime
    version: int
    open_tasks: int
    # The linked asset, when this user can see it (only filled in by get_project).
    asset_id: uuid.UUID | None = None
    asset_name: str | None = None
    asset_kind: str | None = None


@dataclass(frozen=True, slots=True)
class TaskRow:
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    notes: str
    due_at: datetime | None
    due_all_day: bool
    assignee_id: uuid.UUID | None
    position: float
    done_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int
    # Chores (ADR 0013)
    assigned_by: uuid.UUID | None = None
    proof: str = "none"
    repeat_freq: str | None = None
    repeat_interval: int = 1
    repeat_days: list[int] | None = None
    waiting: bool = False  # done by the assignee, waiting for approval


async def role(conn: AsyncConnection, project_id: uuid.UUID) -> str | None:
    value = await conn.scalar(text("SELECT app.project_role(:p)"), {"p": project_id})
    return str(value) if value is not None else None


async def create_project(
    conn: AsyncConnection, *, user_id: uuid.UUID, title: str, description: str, stage: str
) -> uuid.UUID:
    project_id = uuid.uuid7()
    await conn.execute(
        text(
            "INSERT INTO projects (id, title, description, stage, created_by) "
            "VALUES (:id, :t, :d, :s, :u)"
        ),
        {"id": project_id, "t": title, "d": description, "s": stage, "u": user_id},
    )
    await conn.execute(
        text("INSERT INTO project_members (project_id, user_id, role) VALUES (:p, :u, 'owner')"),
        {"p": project_id, "u": user_id},
    )
    return project_id


async def get_project(conn: AsyncConnection, project_id: uuid.UUID) -> ProjectRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT p.id, p.title, p.description, p.stage, p.local_ai_only,
                       app.project_role(p.id) AS role, p.created_at, p.updated_at, p.version,
                       (SELECT count(*) FROM tasks t WHERE t.project_id = p.id
                          AND t.deleted_at IS NULL AND t.done_at IS NULL) AS open_tasks,
                       a.id AS asset_id, a.name AS asset_name, a.kind AS asset_kind
                FROM projects p
                LEFT JOIN assets a ON a.id = p.asset_id AND a.deleted_at IS NULL
                WHERE p.id = :id AND p.deleted_at IS NULL
            """),
            {"id": project_id},
        )
    ).first()
    return ProjectRow(**row._mapping) if row else None


async def list_projects(
    conn: AsyncConnection,
    *,
    stage: str | None,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[ProjectRow]:
    rows = await conn.execute(
        text("""
            SELECT p.id, p.title, p.description, p.stage, p.local_ai_only,
                   app.project_role(p.id) AS role, p.created_at, p.updated_at, p.version,
                   (SELECT count(*) FROM tasks t WHERE t.project_id = p.id
                      AND t.deleted_at IS NULL AND t.done_at IS NULL) AS open_tasks
            FROM projects p
            WHERE p.deleted_at IS NULL AND app.can_read(p.id)
              AND (CAST(:stage AS text) IS NULL OR p.stage = :stage)
              AND (CAST(:after_ts AS timestamptz) IS NULL
                   OR (p.updated_at, p.id) < (CAST(:after_ts AS timestamptz),
                                               CAST(:after_id AS uuid)))
            ORDER BY p.updated_at DESC, p.id DESC
            LIMIT :limit
        """),
        {
            "stage": stage,
            "after_ts": after[0] if after else None,
            "after_id": after[1] if after else None,
            "limit": limit,
        },
    )
    return [ProjectRow(**r._mapping) for r in rows]


async def update_project(
    conn: AsyncConnection,
    project_id: uuid.UUID,
    *,
    expected_version: int,
    title: str | None,
    description: str | None,
    stage: str | None,
    local_ai_only: bool | None,
) -> int | None:
    """Apply the given fields if the version matches. Returns the new version, or None on a
    version mismatch."""
    new_version = await conn.scalar(
        text("""
            UPDATE projects SET
                title = coalesce(CAST(:title AS text), title),
                description = coalesce(CAST(:description AS text), description),
                stage = coalesce(CAST(:stage AS text), stage),
                local_ai_only = coalesce(CAST(:lao AS boolean), local_ai_only),
                updated_at = now(), version = version + 1
            WHERE id = :id AND version = :v AND deleted_at IS NULL
            RETURNING version
        """),
        {
            "id": project_id,
            "v": expected_version,
            "title": title,
            "description": description,
            "stage": stage,
            "lao": local_ai_only,
        },
    )
    return int(new_version) if new_version is not None else None


async def delete_project(conn: AsyncConnection, project_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "UPDATE projects SET deleted_at = now(), updated_at = now(), "
            "version = version + 1 WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": project_id},
    )


async def emit(
    conn: AsyncConnection,
    event_type: str,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """Domain event in the outbox, in the same transaction (ARCHITECTURE.md §8.4)."""
    await conn.execute(
        text(
            "INSERT INTO events (type, user_id, project_id, payload) "
            "VALUES (:t, :u, :p, CAST(:payload AS jsonb))"
        ),
        {"t": event_type, "u": user_id, "p": project_id, "payload": json.dumps(payload)},
    )


# ---------------------------------------------------------------- tasks


async def list_tasks(conn: AsyncConnection, project_id: uuid.UUID) -> list[TaskRow]:
    rows = await conn.execute(
        text("""
            SELECT id, project_id, title, notes, due_at, due_all_day, assignee_id, position,
                   done_at, created_at, updated_at, version, assigned_by, proof, repeat_freq,
                   repeat_interval, repeat_days,
                   EXISTS (SELECT 1 FROM chore_submissions c WHERE c.task_id = tasks.id
                           AND c.status = 'pending'
                           AND c.occurrence_due IS NOT DISTINCT FROM tasks.due_at) AS waiting
            FROM tasks WHERE project_id = :p AND deleted_at IS NULL
            ORDER BY done_at IS NOT NULL, position, created_at
            LIMIT 1000
        """),
        {"p": project_id},
    )
    return [TaskRow(**r._mapping) for r in rows]


async def get_task(conn: AsyncConnection, task_id: uuid.UUID) -> TaskRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, project_id, title, notes, due_at, due_all_day, assignee_id,
                       position, done_at, created_at, updated_at, version, assigned_by, proof,
                       repeat_freq, repeat_interval, repeat_days,
                       EXISTS (SELECT 1 FROM chore_submissions c WHERE c.task_id = tasks.id
                               AND c.status = 'pending'
                               AND c.occurrence_due IS NOT DISTINCT FROM tasks.due_at)
                         AS waiting
                FROM tasks WHERE id = :id AND deleted_at IS NULL
            """),
            {"id": task_id},
        )
    ).first()
    return TaskRow(**row._mapping) if row else None


async def create_task(
    conn: AsyncConnection,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
    notes: str,
    due_at: datetime | None,
    due_all_day: bool,
) -> uuid.UUID:
    task_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO tasks (id, project_id, title, notes, due_at, due_all_day, created_by,
                               position)
            VALUES (:id, :p, :t, :n, :due, :allday, :u,
                    coalesce((SELECT max(position) + 1 FROM tasks WHERE project_id = :p), 0))
        """),
        {
            "id": task_id,
            "p": project_id,
            "t": title,
            "n": notes,
            "due": due_at,
            "allday": due_all_day,
            "u": user_id,
        },
    )
    return task_id


async def update_task(
    conn: AsyncConnection,
    task_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    expected_version: int,
    title: str | None,
    notes: str | None,
    set_due: bool,
    due_at: datetime | None,
    due_all_day: bool | None,
    done: bool | None,
) -> int | None:
    new_version = await conn.scalar(
        text("""
            UPDATE tasks SET
                title = coalesce(CAST(:title AS text), title),
                notes = coalesce(CAST(:notes AS text), notes),
                due_at = CASE WHEN CAST(:set_due AS boolean)
                              THEN CAST(:due_at AS timestamptz) ELSE due_at END,
                due_all_day = coalesce(CAST(:allday AS boolean), due_all_day),
                done_at = CASE WHEN CAST(:done AS boolean) IS NULL THEN done_at
                               WHEN CAST(:done AS boolean) THEN coalesce(done_at, now())
                               ELSE NULL END,
                done_by = CASE WHEN CAST(:done AS boolean) IS NULL THEN done_by
                               WHEN CAST(:done AS boolean) THEN coalesce(done_by, CAST(:u AS uuid))
                               ELSE NULL END,
                updated_at = now(), version = version + 1
            WHERE id = :id AND version = :v AND deleted_at IS NULL
            RETURNING version
        """),
        {
            "id": task_id,
            "v": expected_version,
            "title": title,
            "notes": notes,
            "set_due": set_due,
            "due_at": due_at,
            "allday": due_all_day,
            "done": done,
            "u": user_id,
        },
    )
    return int(new_version) if new_version is not None else None


async def delete_task(conn: AsyncConnection, task_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "UPDATE tasks SET deleted_at = now(), updated_at = now(), version = version + 1 "
            "WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": task_id},
    )


async def title(conn: AsyncConnection, project_id: uuid.UUID) -> str | None:
    """System context helper for notifications."""
    value = await conn.scalar(text("SELECT title FROM projects WHERE id = :p"), {"p": project_id})
    return str(value) if value is not None else None
