"""Projects and tasks API (ARCHITECTURE.md §8.2): cursor pagination, `If-Match` optimistic
concurrency (ETag = version), RFC 9457 errors, 404 for anything the caller can't see."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.services import projects as service
from app.services.projects import ConflictError

router = APIRouter(prefix="/api/v1")

Stage = Literal["idea", "planning", "ready", "in_progress", "done", "archived"]
Title = Annotated[str, Field(min_length=1, max_length=200)]
Text = Annotated[str, Field(max_length=20000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectIn(Strict):
    title: Title
    description: Text = ""
    stage: Stage = "idea"


class ProjectPatch(Strict):
    title: Title | None = None
    description: Text | None = None
    stage: Stage | None = None
    local_ai_only: bool | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    stage: str
    local_ai_only: bool
    role: str | None
    open_tasks: int
    created_at: datetime
    updated_at: datetime
    version: int
    # The linked asset, when you can see it (single-project responses only).
    asset_id: uuid.UUID | None = None
    asset_name: str | None = None
    asset_kind: str | None = None


class ProjectPage(BaseModel):
    items: list[ProjectOut]
    next_cursor: str | None


class TaskIn(Strict):
    title: Annotated[str, Field(min_length=1, max_length=300)]
    notes: Text = ""
    due_at: datetime | None = None
    due_all_day: bool = False


class TaskPatch(Strict):
    title: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    notes: Text | None = None
    due_at: datetime | None = None
    due_all_day: bool | None = None
    done: bool | None = None


class TaskOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    notes: str
    due_at: datetime | None
    due_all_day: bool
    assignee_id: uuid.UUID | None
    done: bool
    done_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


def _project(r: service.ProjectRow) -> ProjectOut:
    return ProjectOut.model_validate(r, from_attributes=True)


def _task(r: service.TaskRow) -> TaskOut:
    return TaskOut(
        id=r.id,
        project_id=r.project_id,
        title=r.title,
        notes=r.notes,
        due_at=r.due_at,
        due_all_day=r.due_all_day,
        assignee_id=r.assignee_id,
        done=r.done_at is not None,
        done_at=r.done_at,
        created_at=r.created_at,
        updated_at=r.updated_at,
        version=r.version,
    )


def _version(if_match: str | None) -> int:  # shared with other routers
    if not if_match:
        raise HTTPException(428, "Send If-Match with the version you are changing.")
    value = if_match.strip().removeprefix("W/").strip('"')
    if not value.isdigit():
        raise HTTPException(400, "If-Match must be a version number.")
    return int(value)


def _etag(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{version}"'


@router.get("/projects")
async def list_projects(
    session: SessionDep,
    request: Request,
    stage: Stage | None = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PAGE)] = 50,
) -> ProjectPage:
    try:
        page = await service.list_projects(
            deps.database(request), session, stage=stage, cursor=cursor, limit=limit
        )
    except ValueError:
        raise HTTPException(400, "Invalid cursor.") from None
    return ProjectPage(items=[_project(r) for r in page.items], next_cursor=page.next_cursor)


@router.post("/projects", status_code=201)
async def create_project(
    body: ProjectIn, session: SessionDep, request: Request, response: Response
) -> ProjectOut:
    row = await service.create_project(
        deps.database(request),
        session,
        title=body.title,
        description=body.description,
        stage=body.stage,
        ip=deps.client_ip(request),
    )
    _etag(response, row.version)
    return _project(row)


@router.get("/projects/{project_id}")
async def get_project(
    project_id: uuid.UUID, session: SessionDep, request: Request, response: Response
) -> ProjectOut:
    row = await service.get_project(deps.database(request), session, project_id)
    _etag(response, row.version)
    return _project(row)


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: uuid.UUID,
    body: ProjectPatch,
    session: SessionDep,
    request: Request,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> ProjectOut:
    try:
        row = await service.update_project(
            deps.database(request),
            session,
            project_id,
            expected_version=_version(if_match),
            title=body.title,
            description=body.description,
            stage=body.stage,
            local_ai_only=body.local_ai_only,
            ip=deps.client_ip(request),
        )
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    _etag(response, row.version)
    return _project(row)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.delete_project(
        deps.database(request), session, project_id, deps.client_ip(request)
    )


@router.get("/projects/{project_id}/tasks")
async def list_tasks(project_id: uuid.UUID, session: SessionDep, request: Request) -> list[TaskOut]:
    rows = await service.list_tasks(deps.database(request), session, project_id)
    return [_task(r) for r in rows]


@router.post("/projects/{project_id}/tasks", status_code=201)
async def create_task(
    project_id: uuid.UUID, body: TaskIn, session: SessionDep, request: Request, response: Response
) -> TaskOut:
    row = await service.create_task(
        deps.database(request),
        session,
        project_id,
        title=body.title,
        notes=body.notes,
        due_at=body.due_at,
        due_all_day=body.due_all_day,
        ip=deps.client_ip(request),
    )
    _etag(response, row.version)
    return _task(row)


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: uuid.UUID,
    body: TaskPatch,
    session: SessionDep,
    request: Request,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> TaskOut:
    try:
        row = await service.update_task(
            deps.database(request),
            session,
            task_id,
            expected_version=_version(if_match),
            title=body.title,
            notes=body.notes,
            set_due="due_at" in body.model_fields_set,
            due_at=body.due_at,
            due_all_day=body.due_all_day,
            done=body.done,
            ip=deps.client_ip(request),
        )
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    _etag(response, row.version)
    return _task(row)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.delete_task(deps.database(request), session, task_id, deps.client_ip(request))
