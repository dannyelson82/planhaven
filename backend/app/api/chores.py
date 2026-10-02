"""Chores (ADR 0013): assigning tasks, the assignee's list and "done" with proof, and the
assigner's approvals."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.attachments import _file
from app.api.deps import SessionDep
from app.api.projects import _etag, _version
from app.services import attachments as attachment_service
from app.services import chores as service
from app.services.projects import ConflictError

router = APIRouter(prefix="/api/v1")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChoreIn(Strict):
    assignee_id: uuid.UUID | None
    proof: Literal["none", "photo", "note"] = "none"
    repeat_freq: Literal["daily", "weekly", "monthly"] | None = None
    repeat_interval: Annotated[int, Field(ge=1, le=52)] = 1
    repeat_days: Annotated[list[Annotated[int, Field(ge=0, le=6)]], Field(max_length=7)] | None = (
        None
    )
    due_at: datetime | None = None
    due_all_day: bool = False


class ChoreOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_title: str | None
    title: str
    notes: str
    due_at: datetime | None
    due_all_day: bool
    done: bool
    assignee_id: uuid.UUID | None
    assigned_by: uuid.UUID | None
    proof: str
    repeat_freq: str | None
    repeat_interval: int
    repeat_days: list[int] | None
    version: int
    status: str | None
    comment: str


class SubmitIn(Strict):
    note: Annotated[str, Field(max_length=2000)] = ""


class SubmissionOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    occurrence_due: datetime | None
    submitted_by: uuid.UUID
    submitted_at: datetime
    note: str
    has_photo: bool
    status: str
    reviewed_at: datetime | None
    comment: str


class ReviewIn(Strict):
    approve: bool
    comment: Annotated[str, Field(max_length=1000)] = ""


class ReviewOut(BaseModel):
    submission: SubmissionOut
    chore: ChoreOut


def _chore(c: service.ChoreRow) -> ChoreOut:
    return ChoreOut(
        id=c.id,
        project_id=c.project_id,
        project_title=c.project_title,
        title=c.title,
        notes=c.notes,
        due_at=c.due_at,
        due_all_day=c.due_all_day,
        done=c.done_at is not None,
        assignee_id=c.assignee_id,
        assigned_by=c.assigned_by,
        proof=c.proof,
        repeat_freq=c.repeat_freq,
        repeat_interval=c.repeat_interval,
        repeat_days=c.repeat_days,
        version=c.version,
        status=c.status,
        comment=c.comment,
    )


def _submission(s: service.SubmissionRow) -> SubmissionOut:
    return SubmissionOut(
        id=s.id,
        task_id=s.task_id,
        occurrence_due=s.occurrence_due,
        submitted_by=s.submitted_by,
        submitted_at=s.submitted_at,
        note=s.note,
        has_photo=s.photo_sha256 is not None,
        status=s.status,
        reviewed_at=s.reviewed_at,
        comment=s.comment,
    )


def _bad(exc: service.ChoreError) -> HTTPException:
    return HTTPException(422, str(exc))


@router.put("/tasks/{task_id}/chore")
async def set_chore(
    task_id: uuid.UUID,
    body: ChoreIn,
    session: SessionDep,
    request: Request,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> ChoreOut:
    try:
        c = await service.set_chore(
            deps.database(request),
            session,
            task_id,
            expected_version=_version(if_match),
            assignee_id=body.assignee_id,
            proof=body.proof,
            repeat_freq=body.repeat_freq,
            repeat_interval=body.repeat_interval,
            repeat_days=body.repeat_days,
            due_at=body.due_at,
            due_all_day=body.due_all_day,
            ip=deps.client_ip(request),
        )
    except service.ChoreError as exc:
        raise _bad(exc) from None
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    _etag(response, c.version)
    return _chore(c)


@router.get("/chores")
async def my_chores(session: SessionDep, request: Request) -> list[ChoreOut]:
    return [_chore(c) for c in await service.mine(deps.database(request), session)]


@router.get("/chores/to-review")
async def to_review(session: SessionDep, request: Request) -> list[ReviewOut]:
    rows = await service.to_review(deps.database(request), session)
    return [ReviewOut(submission=_submission(r.submission), chore=_chore(r.chore)) for r in rows]


@router.post("/tasks/{task_id}/submissions", status_code=201)
async def submit(
    task_id: uuid.UUID, body: SubmitIn, session: SessionDep, request: Request
) -> SubmissionOut:
    try:
        s = await service.submit(
            deps.database(request), session, task_id, body.note, deps.client_ip(request)
        )
    except service.ChoreError as exc:
        raise _bad(exc) from None
    return _submission(s)


@router.get("/tasks/{task_id}/submissions")
async def submissions(
    task_id: uuid.UUID, session: SessionDep, request: Request
) -> list[SubmissionOut]:
    rows = await service.submissions(deps.database(request), session, task_id)
    return [_submission(s) for s in rows]


@router.put("/submissions/{submission_id}/photo")
async def add_photo(
    submission_id: uuid.UUID, session: SessionDep, request: Request
) -> SubmissionOut:
    try:
        s = await service.add_photo(
            deps.database(request),
            deps.blobs(request),
            session,
            submission_id,
            chunks=request.stream(),
            max_bytes=deps.settings(request).max_upload_mb * 1024 * 1024,
            ip=deps.client_ip(request),
        )
    except service.ChoreError as exc:
        raise _bad(exc) from None
    except attachment_service.UploadTooLargeError:
        raise HTTPException(413, "This photo is larger than the upload limit.") from None
    except attachment_service.UnsupportedFileError as exc:
        raise HTTPException(415, str(exc)) from None
    return _submission(s)


@router.post("/submissions/{submission_id}/review")
async def review(
    submission_id: uuid.UUID, body: ReviewIn, session: SessionDep, request: Request
) -> SubmissionOut:
    try:
        s = await service.review(
            deps.database(request),
            session,
            submission_id,
            approve=body.approve,
            comment=body.comment,
            ip=deps.client_ip(request),
        )
    except service.ChoreError as exc:
        raise _bad(exc) from None
    return _submission(s)


@router.get("/submissions/{submission_id}/photo")
async def photo(submission_id: uuid.UUID, session: SessionDep, request: Request) -> FileResponse:
    sha, media = await service.photo(
        deps.database(request), session, submission_id, thumbnail=False
    )
    return _file(request, sha, media, "inline", "proof.jpg")


@router.get("/submissions/{submission_id}/photo/thumbnail")
async def photo_thumbnail(
    submission_id: uuid.UUID, session: SessionDep, request: Request
) -> FileResponse:
    sha, media = await service.photo(deps.database(request), session, submission_id, thumbnail=True)
    return _file(request, sha, media, "inline", "proof.webp")
