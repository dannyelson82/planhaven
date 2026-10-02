"""Chores (ADR 0013, A§21): tasks assigned to someone, once or repeating, with reminders and
optional proof (a photo or a note) that the person who assigned it approves or sends back.

The assignee sees and completes their chores without being a member of the project (RLS lets
them read the task). Their "done" is written in system context, after authz.require_chore has
checked that they are the assignee: the project's own write rules don't apply to them.
"""

import calendar
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app import authz
from app.db import auth as audit
from app.db import chores as store
from app.db import messages as people_store
from app.db import notifications as notification_store
from app.db import projects as project_store
from app.db.database import Database
from app.services import attachments as attachment_service
from app.services import live
from app.services.auth import CurrentSession
from app.services.notifications import zone
from app.services.projects import ConflictError

ChoreRow = store.ChoreRow
SubmissionRow = store.SubmissionRow
PROOFS = ("none", "photo", "note")
FREQS = ("daily", "weekly", "monthly")
REMIND_AFTER = timedelta(hours=3)  # a second nudge if it's still not done


class ChoreError(ValueError):
    """A request that can't be done as asked (shown to the person)."""


# ---------------------------------------------------------------- repeating


def _add_months(day: date, months: int) -> date:
    total = day.month - 1 + months
    year, month = day.year + total // 12, total % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def next_due(
    due: datetime,
    freq: str,
    interval: int,
    days: list[int] | None,
    tz: ZoneInfo,
    after: datetime,
) -> datetime:
    """The next time a repeating chore is due after `after`, at the same local time of day.
    Weekly `days` are 0 = Sunday ... 6 = Saturday; with an interval of N weeks, only every Nth
    week counts (from the week of the first due date). Missed occurrences are skipped."""
    local = due.astimezone(tz)
    at = local.timetz().replace(tzinfo=None)
    start = local.date()

    def when(day: date) -> datetime:
        return datetime.combine(day, at, tzinfo=tz).astimezone(UTC)

    if freq == "monthly":
        for k in range(1, 1200):
            if (candidate := when(_add_months(start, interval * k))) > after:
                return candidate
    elif freq == "daily":
        for k in range(1, 20000):
            if (candidate := when(start + timedelta(days=interval * k))) > after:
                return candidate
    else:  # weekly: on the chosen days (or the first due date's weekday), every Nth week
        wanted = set(days) if days else {(start.weekday() + 1) % 7}
        sunday = start - timedelta(days=(start.weekday() + 1) % 7)
        day = start
        for _ in range(20000):
            day += timedelta(days=1)
            in_week = ((day - sunday).days // 7) % interval == 0
            if in_week and (day.weekday() + 1) % 7 in wanted and (candidate := when(day)) > after:
                return candidate
    raise ChoreError("This repeat rule doesn't give a next date.")


# ---------------------------------------------------------------- access


async def _access(
    conn: Any, session: CurrentSession, task_id: uuid.UUID
) -> tuple[ChoreRow, authz.ChoreAccess]:
    chore = await store.get(conn, task_id)
    if chore is None:
        raise authz.NotFoundError("Not found.")
    role = await project_store.role(conn, chore.project_id)
    me = session.user.id
    return chore, authz.ChoreAccess(chore.assignee_id == me, chore.assigned_by == me, role)


async def _notify(
    db: Database, user_id: uuid.UUID | None, kind: str, chore: ChoreRow, **extra: Any
) -> None:
    if user_id is None:
        return
    async with db.system_transaction() as conn:
        await notification_store.notify(
            conn,
            user_id,
            kind,
            {"title": chore.title[:120], "task_id": str(chore.id), **extra},
        )
    live.publish_to(user_id, "notifications")


# ---------------------------------------------------------------- assigning (project editors)


async def set_chore(
    db: Database,
    session: CurrentSession,
    task_id: uuid.UUID,
    *,
    expected_version: int,
    assignee_id: uuid.UUID | None,
    proof: str,
    repeat_freq: str | None,
    repeat_interval: int,
    repeat_days: list[int] | None,
    due_at: datetime | None,
    due_all_day: bool,
    ip: str | None,
) -> ChoreRow:
    """Assign a task (or stop assigning it), with its proof and repeat rule and due time."""
    if proof not in PROOFS or (repeat_freq is not None and repeat_freq not in FREQS):
        raise ChoreError("Unknown setting.")
    if repeat_freq is not None and due_at is None:
        raise ChoreError("A repeating chore needs a first due date and time.")
    if repeat_freq != "weekly":
        repeat_days = None
    elif repeat_days is not None:
        repeat_days = sorted(set(repeat_days))
        if not repeat_days or any(d not in range(7) for d in repeat_days):
            raise ChoreError("Choose the days of the week.")
    if assignee_id is not None:
        async with db.system_transaction() as conn:
            if not await people_store.active(conn, assignee_id):
                raise authz.NotFoundError("Not found.")
    me = session.user.id
    async with db.user_transaction(me) as conn:
        before, _ = await _access(conn, session, task_id)
        access = authz.ProjectAccess(await project_store.role(conn, before.project_id))
        authz.require(session.principal, authz.Action.PROJECT_EDIT, access)
        version = await store.set_chore(
            conn,
            task_id,
            expected_version=expected_version,
            assignee_id=assignee_id,
            assigned_by=me if assignee_id is not None else None,
            proof=proof if assignee_id is not None else "none",
            repeat_freq=repeat_freq,
            repeat_interval=repeat_interval,
            repeat_days=repeat_days,
            due_at=due_at,
            due_all_day=due_all_day if repeat_freq is None else False,
        )
        if version is None:
            raise ConflictError("This task was changed elsewhere. Reload and try again.")
        await audit.record_audit(
            conn,
            action="chore.assigned" if assignee_id else "chore.unassigned",
            actor_user_id=me,
            ip=ip,
            project_id=before.project_id,
            resource_type="task",
            resource_id=task_id,
        )
        after = await store.get(conn, task_id)
    if after is None:
        raise authz.NotFoundError("Not found.")
    if assignee_id is not None and assignee_id != me and assignee_id != before.assignee_id:
        await _notify(db, assignee_id, "chore_assigned", after, by=session.user.display_name[:80])
    live.publish(before.project_id, "tasks")
    return after


# ---------------------------------------------------------------- the assignee


async def mine(db: Database, session: CurrentSession) -> list[ChoreRow]:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        return await store.assigned_to(conn, session.user.id)


def _needs_review(chore: ChoreRow, me: uuid.UUID) -> bool:
    return chore.proof != "none" and chore.assigned_by is not None and chore.assigned_by != me


async def _finish(db: Database, chore: ChoreRow, done_by: uuid.UUID) -> None:
    """One occurrence done (system context): repeat, or mark the task done."""
    following = None
    if chore.repeat_freq is not None and chore.due_at is not None:
        async with db.system_transaction() as conn:
            zones = await notification_store.settings_for(conn, [done_by])
        following = next_due(
            chore.due_at,
            chore.repeat_freq,
            chore.repeat_interval,
            chore.repeat_days,
            zone(zones.get(done_by, "UTC")),
            datetime.now(UTC),
        )
    async with db.system_transaction() as conn:
        await store.complete(conn, chore.id, done_by=done_by, next_due=following)
    live.publish(chore.project_id, "tasks")


async def submit(
    db: Database, session: CurrentSession, task_id: uuid.UUID, note: str, ip: str | None
) -> SubmissionRow:
    """The assignee says it's done. No proof needed: done (or on to the next time). A photo:
    waits for the photo. Otherwise it waits for the assigner's approval."""
    me = session.user.id
    note = note.strip()
    async with db.user_transaction(me) as conn:
        chore, access = await _access(conn, session, task_id)
    authz.require_chore(session.principal, authz.Action.CHORE_COMPLETE, access)
    if chore.done_at is not None:
        raise ChoreError("This is already done.")
    if chore.status == "pending":
        raise ChoreError("This is already waiting for approval.")
    if chore.proof == "note" and not note:
        raise ChoreError("Add a note to say what you did.")
    if chore.proof == "photo":
        status = "awaiting_photo"
    elif _needs_review(chore, me):
        status = "pending"
    else:
        status = "approved"
    async with db.system_transaction() as conn:
        submission_id = await store.add_submission(
            conn,
            task_id=task_id,
            project_id=chore.project_id,
            occurrence_due=chore.due_at,
            submitted_by=me,
            note=note[:2000],
            status=status,
        )
        await audit.record_audit(
            conn,
            action="chore.submitted",
            actor_user_id=me,
            ip=ip,
            project_id=chore.project_id,
            resource_type="task",
            resource_id=task_id,
        )
        row = await store.get_submission(conn, submission_id)
    if status == "approved":
        await _finish(db, chore, me)
    elif status == "pending":
        await _notify(
            db, chore.assigned_by, "chore_submitted", chore, by=session.user.display_name[:80]
        )
    if row is None:
        raise RuntimeError("submission not written")
    return row


async def add_photo(
    db: Database,
    blobs: attachment_service.BlobStore,
    session: CurrentSession,
    submission_id: uuid.UUID,
    *,
    chunks: AsyncIterator[bytes],
    max_bytes: int,
    ip: str | None,
) -> SubmissionRow:
    """The proof photo for a submission (cleaned like any photo: no location)."""
    me = session.user.id
    async with db.user_transaction(me) as conn:
        submission = await store.get_submission(conn, submission_id)
        if submission is None:
            raise authz.NotFoundError("Not found.")
        chore, access = await _access(conn, session, submission.task_id)
    authz.require_chore(session.principal, authz.Action.CHORE_COMPLETE, access)
    if submission.submitted_by != me or submission.status not in ("awaiting_photo", "pending"):
        raise ChoreError("This can't take a photo any more.")
    photo, thumb, content_type = await attachment_service.receive_photo(
        db, blobs, session, chunks=chunks, max_bytes=max_bytes, ip=ip
    )
    status = "pending" if _needs_review(chore, me) else "approved"
    async with db.system_transaction() as conn:
        await store.set_photo(
            conn, submission_id, photo=photo, thumb=thumb, content_type=content_type, status=status
        )
        row = await store.get_submission(conn, submission_id)
    if status == "approved":
        await _finish(db, chore, me)
    elif submission.status == "awaiting_photo":
        await _notify(
            db, chore.assigned_by, "chore_submitted", chore, by=session.user.display_name[:80]
        )
    if row is None:
        raise authz.NotFoundError("Not found.")
    return row


# ---------------------------------------------------------------- the assigner


@dataclass(frozen=True, slots=True)
class Review:
    submission: SubmissionRow
    chore: ChoreRow


async def to_review(db: Database, session: CurrentSession) -> list[Review]:
    authz.require(session.principal, authz.Action.USE_APP)
    out = []
    async with db.user_transaction(session.user.id) as conn:
        for s in await store.pending_for_reviewer(conn, session.user.id):
            chore = await store.get(conn, s.task_id)
            if chore is not None:
                out.append(Review(s, chore))
    return out


async def submissions(
    db: Database, session: CurrentSession, task_id: uuid.UUID
) -> list[SubmissionRow]:
    async with db.user_transaction(session.user.id) as conn:
        _, access = await _access(conn, session, task_id)
        authz.require_chore(session.principal, authz.Action.CHORE_VIEW, access)
        return await store.submissions_for(conn, task_id)


async def review(
    db: Database,
    session: CurrentSession,
    submission_id: uuid.UUID,
    *,
    approve: bool,
    comment: str,
    ip: str | None,
) -> SubmissionRow:
    me = session.user.id
    async with db.user_transaction(me) as conn:
        submission = await store.get_submission(conn, submission_id)
        if submission is None:
            raise authz.NotFoundError("Not found.")
        chore, access = await _access(conn, session, submission.task_id)
    authz.require_chore(session.principal, authz.Action.CHORE_REVIEW, access)
    if submission.status != "pending":
        raise ChoreError("This isn't waiting for approval.")
    comment = comment.strip()[:1000]
    if not approve and not comment:
        raise ChoreError("Say what still needs doing.")
    async with db.system_transaction() as conn:
        await store.review(
            conn,
            submission_id,
            status="approved" if approve else "sent_back",
            reviewer=me,
            comment=comment,
        )
        await audit.record_audit(
            conn,
            action="chore.approved" if approve else "chore.sent_back",
            actor_user_id=me,
            ip=ip,
            project_id=chore.project_id,
            resource_type="task",
            resource_id=chore.id,
        )
        row = await store.get_submission(conn, submission_id)
    if approve:
        await _finish(db, chore, submission.submitted_by)
    await _notify(
        db, submission.submitted_by, "chore_approved" if approve else "chore_sent_back", chore
    )
    if row is None:
        raise authz.NotFoundError("Not found.")
    return row


async def photo(
    db: Database, session: CurrentSession, submission_id: uuid.UUID, *, thumbnail: bool
) -> tuple[str, str]:
    """(blob, content type) of a proof photo, for the assignee, assigner and project members."""
    async with db.user_transaction(session.user.id) as conn:
        submission = await store.get_submission(conn, submission_id)
        if submission is None:
            raise authz.NotFoundError("Not found.")
        _, access = await _access(conn, session, submission.task_id)
    authz.require_chore(session.principal, authz.Action.CHORE_VIEW, access)
    if submission.photo_sha256 is None or submission.photo_thumb_sha256 is None:
        raise authz.NotFoundError("No photo.")
    if thumbnail:
        return submission.photo_thumb_sha256, "image/webp"
    return submission.photo_sha256, submission.photo_type or "image/jpeg"


# ---------------------------------------------------------------- reminders (the worker)


async def remind(db: Database, *, now: datetime | None = None) -> int:
    """Chores that are due: tell the assignee once, and once more if still not done a few
    hours later (title only)."""
    now = now or datetime.now(UTC)
    added = 0
    async with db.system_transaction() as conn:
        for c in await store.due_chores(conn):
            data = {"title": c.title[:120], "task_id": str(c.id)}
            due = c.due_at.astimezone(UTC).isoformat()
            added += await notification_store.notify(
                conn, c.assignee_id, "chore_due", data, f"chore_due:{c.id}:{due}"
            )
            if now - c.due_at >= REMIND_AFTER:
                added += await notification_store.notify(
                    conn, c.assignee_id, "chore_reminder", data, f"chore_reminder:{c.id}:{due}"
                )
    return added
