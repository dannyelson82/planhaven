"""Job queue storage (ADR 0003). SQL only; the worker loop lives in app.workers."""

import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

MAX_PAYLOAD_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    user_id: uuid.UUID | None
    attempts: int
    max_attempts: int


async def enqueue(
    conn: AsyncConnection,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    user_id: uuid.UUID | None,
    delay: timedelta = timedelta(0),
    max_attempts: int = 5,
) -> uuid.UUID:
    """Add a job inside the caller's transaction, so it exists only if the change that caused
    it commits. `user_id` must be the transaction's user (RLS enforces it) or None in system
    context."""
    body = json.dumps(payload or {})
    if len(body.encode()) > MAX_PAYLOAD_BYTES:
        raise ValueError("job payload too large; store data in a table and pass its ID")
    # The ID is generated here, not RETURNed: users may add jobs but not read the queue, and
    # RETURNING would need read access to the new row.
    job_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO jobs (id, kind, payload, user_id, run_after, max_attempts)
            VALUES (:id, :kind, CAST(:payload AS jsonb), :user_id, now() + :delay,
                    :max_attempts)
        """),
        {
            "id": job_id,
            "kind": kind,
            "payload": body,
            "user_id": user_id,
            "delay": delay,
            "max_attempts": max_attempts,
        },
    )
    return job_id


async def claim(conn: AsyncConnection, lease: timedelta) -> ClaimedJob | None:
    """Claim one due job (or one whose previous worker died mid-run). Runs in system context.
    SKIP LOCKED lets several workers claim different jobs without blocking each other."""
    row = (
        await conn.execute(
            text("""
                WITH next AS (
                    SELECT id FROM jobs
                    WHERE (status = 'queued' AND run_after <= now())
                       OR (status = 'running' AND locked_until < now())
                    ORDER BY run_after
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE jobs SET status = 'running', attempts = jobs.attempts + 1,
                                locked_until = now() + :lease, updated_at = now()
                FROM next WHERE jobs.id = next.id
                RETURNING jobs.id, jobs.kind, jobs.payload, jobs.user_id, jobs.attempts,
                          jobs.max_attempts
            """),
            {"lease": lease},
        )
    ).first()
    if row is None:
        return None
    return ClaimedJob(
        id=row.id,
        kind=row.kind,
        payload=row.payload if isinstance(row.payload, dict) else json.loads(row.payload),
        user_id=row.user_id,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
    )


async def mark_done(conn: AsyncConnection, job_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "UPDATE jobs SET status = 'done', locked_until = NULL, last_error = NULL, "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": job_id},
    )


async def mark_failed(
    conn: AsyncConnection, job: ClaimedJob, error: str, retry_in: timedelta | None
) -> None:
    """Requeue after `retry_in`, or mark dead when attempts are used up (retry_in None)."""
    await conn.execute(
        text("""
            UPDATE jobs SET status = :status, locked_until = NULL, last_error = :error,
                            run_after = now() + :retry_in, updated_at = now()
            WHERE id = :id
        """),
        {
            "id": job.id,
            "status": "queued" if retry_in is not None else "dead",
            "error": error[:200],
            "retry_in": retry_in or timedelta(0),
        },
    )


async def heartbeat(conn: AsyncConnection, worker_id: str) -> None:
    await conn.execute(
        text("""
            INSERT INTO worker_heartbeats (worker_id, seen_at) VALUES (:w, now())
            ON CONFLICT (worker_id) DO UPDATE SET seen_at = now()
        """),
        {"w": worker_id},
    )


async def newest_heartbeat_age(conn: AsyncConnection) -> timedelta | None:
    age = await conn.scalar(text("SELECT now() - max(seen_at) FROM worker_heartbeats"))
    return age if isinstance(age, timedelta) else None
