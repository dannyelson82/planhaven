"""Queries for chores (ADR 0013): assignment and repeat settings on tasks, and submissions.
Reads are user transactions (RLS: project members or the assignee); writes that the assignee
causes run in system context after the service's authorization check."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class ChoreRow:
    id: uuid.UUID
    project_id: uuid.UUID
    project_title: str | None  # None when the person isn't a project member
    title: str
    notes: str
    due_at: datetime | None
    due_all_day: bool
    done_at: datetime | None
    assignee_id: uuid.UUID | None
    assigned_by: uuid.UUID | None
    proof: str
    repeat_freq: str | None
    repeat_interval: int
    repeat_days: list[int] | None
    version: int
    status: str | None  # the latest submission's status for this occurrence
    comment: str  # the latest "sent back" comment


async def _chores(
    conn: AsyncConnection, *, task_id: uuid.UUID | None, assignee: uuid.UUID | None
) -> list[ChoreRow]:
    rows = await conn.execute(
        text("""
            SELECT t.id, t.project_id, p.title AS project_title, t.title, t.notes, t.due_at,
                   t.due_all_day, t.done_at, t.assignee_id, t.assigned_by, t.proof,
                   t.repeat_freq, t.repeat_interval, t.repeat_days, t.version,
                   s.status, coalesce(s.comment, '') AS comment
            FROM tasks t
            LEFT JOIN projects p ON p.id = t.project_id AND p.deleted_at IS NULL
            LEFT JOIN LATERAL (
                SELECT status, comment FROM chore_submissions c
                WHERE c.task_id = t.id AND c.occurrence_due IS NOT DISTINCT FROM t.due_at
                ORDER BY c.submitted_at DESC LIMIT 1
            ) s ON true
            WHERE t.deleted_at IS NULL
              AND (CAST(:id AS uuid) IS NULL OR t.id = :id)
              AND (CAST(:u AS uuid) IS NULL OR (t.assignee_id = :u AND t.done_at IS NULL))
            ORDER BY t.due_at NULLS LAST, t.created_at LIMIT 200
        """),
        {"id": task_id, "u": assignee},
    )
    return [ChoreRow(**r._mapping) for r in rows]


async def get(conn: AsyncConnection, task_id: uuid.UUID) -> ChoreRow | None:
    found = await _chores(conn, task_id=task_id, assignee=None)
    return found[0] if found else None


async def assigned_to(conn: AsyncConnection, user_id: uuid.UUID) -> list[ChoreRow]:
    """Open chores assigned to this person (RLS lets them see these without membership)."""
    return await _chores(conn, task_id=None, assignee=user_id)


async def set_chore(
    conn: AsyncConnection,
    task_id: uuid.UUID,
    *,
    expected_version: int,
    assignee_id: uuid.UUID | None,
    assigned_by: uuid.UUID | None,
    proof: str,
    repeat_freq: str | None,
    repeat_interval: int,
    repeat_days: list[int] | None,
    due_at: datetime | None,
    due_all_day: bool,
) -> int | None:
    v = await conn.scalar(
        text("""
            UPDATE tasks SET assignee_id = :a, assigned_by = :by, proof = :p,
                   repeat_freq = :f, repeat_interval = :i, repeat_days = CAST(:d AS smallint[]),
                   due_at = :due, due_all_day = :all_day,
                   updated_at = now(), version = version + 1
            WHERE id = :id AND version = :v AND deleted_at IS NULL RETURNING version
        """),
        {
            "id": task_id,
            "v": expected_version,
            "a": assignee_id,
            "by": assigned_by,
            "p": proof,
            "f": repeat_freq,
            "i": repeat_interval,
            "d": repeat_days,
            "due": due_at,
            "all_day": due_all_day,
        },
    )
    return int(v) if v is not None else None


@dataclass(frozen=True, slots=True)
class SubmissionRow:
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    occurrence_due: datetime | None
    submitted_by: uuid.UUID
    submitted_at: datetime
    note: str
    photo_sha256: str | None
    photo_thumb_sha256: str | None
    photo_type: str | None
    status: str
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    comment: str


async def _submissions(
    conn: AsyncConnection, *, submission_id: uuid.UUID | None, task_id: uuid.UUID | None
) -> list[SubmissionRow]:
    rows = await conn.execute(
        text("""
            SELECT id, task_id, project_id, occurrence_due, submitted_by, submitted_at, note,
                   photo_sha256, photo_thumb_sha256, photo_type, status, reviewed_by,
                   reviewed_at, comment
            FROM chore_submissions
            WHERE (CAST(:id AS uuid) IS NULL OR id = :id)
              AND (CAST(:t AS uuid) IS NULL OR task_id = :t)
            ORDER BY submitted_at DESC LIMIT 50
        """),
        {"id": submission_id, "t": task_id},
    )
    return [SubmissionRow(**r._mapping) for r in rows]


async def get_submission(conn: AsyncConnection, submission_id: uuid.UUID) -> SubmissionRow | None:
    found = await _submissions(conn, submission_id=submission_id, task_id=None)
    return found[0] if found else None


async def submissions_for(conn: AsyncConnection, task_id: uuid.UUID) -> list[SubmissionRow]:
    return await _submissions(conn, submission_id=None, task_id=task_id)


async def pending_for_reviewer(conn: AsyncConnection, user_id: uuid.UUID) -> list[SubmissionRow]:
    """Submissions waiting for this person: chores they assigned (RLS: projects they're in)."""
    rows = await conn.execute(
        text("""
            SELECT c.id, c.task_id, c.project_id, c.occurrence_due, c.submitted_by,
                   c.submitted_at, c.note, c.photo_sha256, c.photo_thumb_sha256, c.photo_type,
                   c.status, c.reviewed_by, c.reviewed_at, c.comment
            FROM chore_submissions c JOIN tasks t ON t.id = c.task_id AND t.deleted_at IS NULL
            WHERE c.status = 'pending' AND t.assigned_by = :u
            ORDER BY c.submitted_at LIMIT 200
        """),
        {"u": user_id},
    )
    return [SubmissionRow(**r._mapping) for r in rows]


# ---------------------------------------------------------------- system context


async def add_submission(
    conn: AsyncConnection,
    *,
    task_id: uuid.UUID,
    project_id: uuid.UUID,
    occurrence_due: datetime | None,
    submitted_by: uuid.UUID,
    note: str,
    status: str,
) -> uuid.UUID:
    submission_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO chore_submissions (id, task_id, project_id, occurrence_due, submitted_by,
                                           note, status)
            VALUES (:id, :t, :p, :o, :u, :n, :s)
        """),
        {
            "id": submission_id,
            "t": task_id,
            "p": project_id,
            "o": occurrence_due,
            "u": submitted_by,
            "n": note,
            "s": status,
        },
    )
    return submission_id


async def set_photo(
    conn: AsyncConnection,
    submission_id: uuid.UUID,
    *,
    photo: str,
    thumb: str,
    content_type: str,
    status: str,
) -> None:
    await conn.execute(
        text("""
            UPDATE chore_submissions SET photo_sha256 = :p, photo_thumb_sha256 = :t,
                   photo_type = :ct, status = :s
            WHERE id = :id
        """),
        {"id": submission_id, "p": photo, "t": thumb, "ct": content_type, "s": status},
    )


async def review(
    conn: AsyncConnection,
    submission_id: uuid.UUID,
    *,
    status: str,
    reviewer: uuid.UUID | None,
    comment: str,
) -> None:
    await conn.execute(
        text("""
            UPDATE chore_submissions SET status = :s, reviewed_by = :r, reviewed_at = now(),
                   comment = :c
            WHERE id = :id
        """),
        {"id": submission_id, "s": status, "r": reviewer, "c": comment},
    )


async def complete(
    conn: AsyncConnection, task_id: uuid.UUID, *, done_by: uuid.UUID, next_due: datetime | None
) -> None:
    """One occurrence done: a repeating chore moves to its next due time; a one-off is done."""
    if next_due is not None:
        await conn.execute(
            text("""
                UPDATE tasks SET due_at = :n, updated_at = now(), version = version + 1
                WHERE id = :id
            """),
            {"id": task_id, "n": next_due},
        )
    else:
        await conn.execute(
            text("""
                UPDATE tasks SET done_at = now(), done_by = :u, updated_at = now(),
                       version = version + 1
                WHERE id = :id AND done_at IS NULL
            """),
            {"id": task_id, "u": done_by},
        )


@dataclass(frozen=True, slots=True)
class DueChoreRow:
    id: uuid.UUID
    title: str
    due_at: datetime
    assignee_id: uuid.UUID


async def due_chores(conn: AsyncConnection) -> list[DueChoreRow]:
    """Open chores due in the last two days, with no submission yet for that occurrence."""
    rows = await conn.execute(
        text("""
            SELECT t.id, t.title, t.due_at, t.assignee_id
            FROM tasks t
            JOIN projects p ON p.id = t.project_id AND p.deleted_at IS NULL
            JOIN users u ON u.id = t.assignee_id AND u.disabled_at IS NULL
            WHERE t.deleted_at IS NULL AND t.done_at IS NULL AND t.assignee_id IS NOT NULL
              AND t.due_at BETWEEN now() - interval '2 days' AND now()
              AND NOT EXISTS (SELECT 1 FROM chore_submissions c WHERE c.task_id = t.id
                              AND c.occurrence_due = t.due_at
                              AND c.status IN ('pending', 'approved', 'awaiting_photo'))
            LIMIT 5000
        """)
    )
    return [DueChoreRow(**r._mapping) for r in rows]
