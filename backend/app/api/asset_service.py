"""Asset service: meter readings, maintenance schedules and service records."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.api.projects import _etag, _version
from app.services import asset_service as service
from app.services.projects import ConflictError

router = APIRouter(prefix="/api/v1", tags=["assets"])

Distance = Annotated[Decimal, Field(ge=0, le=Decimal("99999999"), max_digits=12, decimal_places=1)]
Hours = Annotated[Decimal, Field(ge=0, le=Decimal("9999999"), max_digits=10, decimal_places=1)]
EveryDistance = Annotated[
    Decimal, Field(gt=0, le=Decimal("9999999"), max_digits=12, decimal_places=1)
]
EveryHours = Annotated[Decimal, Field(gt=0, le=Decimal("999999"), max_digits=10, decimal_places=1)]
EveryMonths = Annotated[int, Field(ge=1, le=240)]
Notes = Annotated[str, Field(max_length=4000)]
Day = Annotated[date, Field(ge=date(1900, 1, 1), le=date(2200, 12, 31))]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UnitIn(Strict):
    unit: Literal["km", "mi"]


class ReadingIn(Strict):
    read_on: Day
    distance: Distance | None = None
    hours: Hours | None = None


class ScheduleIn(Strict):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    every_distance: EveryDistance | None = None
    every_hours: EveryHours | None = None
    every_months: EveryMonths | None = None
    notes: Notes = ""


class RecordIn(Strict):
    schedule_id: uuid.UUID | None = None
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    done_on: Day
    distance: Distance | None = None
    hours: Hours | None = None
    cost_cents: Annotated[int, Field(ge=0, le=100_000_000_000)] | None = None
    notes: Notes = ""


class ReadingOut(BaseModel):
    id: uuid.UUID
    read_on: date
    distance: Decimal | None
    hours: Decimal | None


class RecordOut(BaseModel):
    id: uuid.UUID
    schedule_id: uuid.UUID | None
    title: str
    done_on: date
    distance: Decimal | None
    hours: Decimal | None
    cost_cents: int | None
    notes: str


class ScheduleOut(BaseModel):
    id: uuid.UUID
    name: str
    every_distance: Decimal | None
    every_hours: Decimal | None
    every_months: int | None
    notes: str
    version: int
    last_done_on: date | None = None
    status: Literal["overdue", "soon", "ok", "unknown"] = "unknown"
    due_on: date | None = None
    due_distance: Decimal | None = None
    due_hours: Decimal | None = None


class ServiceOut(BaseModel):
    distance_unit: str
    distance: Decimal | None
    hours: Decimal | None
    readings: list[ReadingOut]
    schedules: list[ScheduleOut]
    records: list[RecordOut]
    can_edit: bool


def _schedule(s: service.ScheduleRow, status: service.ScheduleStatus | None = None) -> ScheduleOut:
    out = ScheduleOut.model_validate(s, from_attributes=True)
    if status is None:
        return out
    return out.model_copy(
        update={
            "last_done_on": status.last.done_on if status.last else None,
            "status": status.due.status,
            "due_on": status.due.due_on,
            "due_distance": status.due.due_distance,
            "due_hours": status.due.due_hours,
        }
    )


def _bad(exc: service.ServiceError) -> HTTPException:
    return HTTPException(422, str(exc))


@router.get("/assets/{asset_id}/service")
async def get_service(asset_id: uuid.UUID, session: SessionDep, request: Request) -> ServiceOut:
    v = await service.view(deps.database(request), session, asset_id)
    return ServiceOut(
        distance_unit=v.distance_unit,
        distance=v.distance,
        hours=v.hours,
        readings=[ReadingOut.model_validate(r, from_attributes=True) for r in v.readings],
        schedules=[_schedule(s.schedule, s) for s in v.schedules],
        records=[RecordOut.model_validate(r, from_attributes=True) for r in v.records],
        can_edit=v.can_edit,
    )


@router.put("/assets/{asset_id}/distance-unit", status_code=204)
async def set_distance_unit(
    asset_id: uuid.UUID, body: UnitIn, session: SessionDep, request: Request
) -> None:
    await service.set_distance_unit(deps.database(request), session, asset_id, body.unit)


@router.post("/assets/{asset_id}/readings", status_code=204)
async def add_reading(
    asset_id: uuid.UUID, body: ReadingIn, session: SessionDep, request: Request
) -> None:
    try:
        await service.add_reading(
            deps.database(request),
            session,
            asset_id,
            read_on=body.read_on,
            distance=body.distance,
            hours=body.hours,
            ip=deps.client_ip(request),
        )
    except service.ServiceError as exc:
        raise _bad(exc) from None


@router.delete("/asset-readings/{reading_id}", status_code=204)
async def delete_reading(reading_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.delete_reading(
        deps.database(request), session, reading_id, deps.client_ip(request)
    )


@router.post("/assets/{asset_id}/service-schedules", status_code=201)
async def create_schedule(
    asset_id: uuid.UUID, body: ScheduleIn, session: SessionDep, request: Request
) -> ScheduleOut:
    try:
        row = await service.create_schedule(
            deps.database(request),
            session,
            asset_id,
            name=body.name,
            every_distance=body.every_distance,
            every_hours=body.every_hours,
            every_months=body.every_months,
            notes=body.notes,
            ip=deps.client_ip(request),
        )
    except service.ServiceError as exc:
        raise _bad(exc) from None
    return _schedule(row)


@router.put("/service-schedules/{schedule_id}")
async def update_schedule(
    schedule_id: uuid.UUID,
    body: ScheduleIn,
    session: SessionDep,
    request: Request,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> ScheduleOut:
    try:
        row = await service.update_schedule(
            deps.database(request),
            session,
            schedule_id,
            expected_version=_version(if_match),
            name=body.name,
            every_distance=body.every_distance,
            every_hours=body.every_hours,
            every_months=body.every_months,
            notes=body.notes,
            ip=deps.client_ip(request),
        )
    except service.ServiceError as exc:
        raise _bad(exc) from None
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    _etag(response, row.version)
    return _schedule(row)


@router.delete("/service-schedules/{schedule_id}", status_code=204)
async def delete_schedule(schedule_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.delete_schedule(
        deps.database(request), session, schedule_id, deps.client_ip(request)
    )


@router.post("/assets/{asset_id}/service-records", status_code=201)
async def add_record(
    asset_id: uuid.UUID, body: RecordIn, session: SessionDep, request: Request
) -> RecordOut:
    try:
        row = await service.add_record(
            deps.database(request),
            session,
            asset_id,
            schedule_id=body.schedule_id,
            title=body.title,
            done_on=body.done_on,
            distance=body.distance,
            hours=body.hours,
            cost_cents=body.cost_cents,
            notes=body.notes,
            ip=deps.client_ip(request),
        )
    except service.ServiceError as exc:
        raise _bad(exc) from None
    return RecordOut.model_validate(row, from_attributes=True)


@router.delete("/service-records/{record_id}", status_code=204)
async def delete_record(record_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.delete_record(deps.database(request), session, record_id, deps.client_ip(request))
