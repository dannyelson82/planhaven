"""Lists API: lists per project, and their items."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.api.projects import _etag, _version
from app.services import lists as service
from app.services.projects import ConflictError

router = APIRouter(prefix="/api/v1")

Kind = Literal["shopping", "parts", "checklist"]
Qty = Annotated[Decimal, Field(ge=0, le=Decimal("999999999"), max_digits=12, decimal_places=3)]
Price = Annotated[int, Field(ge=0, le=10**12)]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=8, max_length=100)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListIn(Strict):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    kind: Kind = "shopping"


class ListPatch(Strict):
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    kind: Kind | None = None


class ListOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    kind: str
    open_items: int
    total_items: int
    updated_at: datetime
    version: int


class ItemIn(Strict):
    text: Annotated[str, Field(min_length=1, max_length=500)]
    quantity: Qty | None = None
    unit: Annotated[str, Field(max_length=30)] | None = None
    price_cents: Price | None = None


class ItemPatch(Strict):
    text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    quantity: Qty | None = None
    unit: Annotated[str, Field(max_length=30)] | None = None
    price_cents: Price | None = None
    checked: bool | None = None


class ItemOut(BaseModel):
    id: uuid.UUID
    list_id: uuid.UUID
    text: str
    quantity: Decimal | None
    unit: str | None
    price_cents: int | None
    checked: bool
    updated_at: datetime
    version: int


class ListWithItems(ListOut):
    items: list[ItemOut]


def _list(r: service.ListRow) -> ListOut:
    return ListOut.model_validate(r, from_attributes=True)


def _item(r: service.ItemRow) -> ItemOut:
    return ItemOut(
        id=r.id,
        list_id=r.list_id,
        text=r.text,
        quantity=r.quantity,
        unit=r.unit,
        price_cents=r.price_cents,
        checked=r.checked_at is not None,
        updated_at=r.updated_at,
        version=r.version,
    )


@router.get("/projects/{project_id}/lists")
async def lists_for_project(
    project_id: uuid.UUID, session: SessionDep, request: Request
) -> list[ListOut]:
    rows = await service.lists_for_project(deps.database(request), session, project_id)
    return [_list(r) for r in rows]


@router.post("/projects/{project_id}/lists", status_code=201)
async def create_list(
    project_id: uuid.UUID, body: ListIn, session: SessionDep, request: Request, response: Response
) -> ListOut:
    row = await service.create_list(
        deps.database(request),
        session,
        project_id,
        title=body.title,
        kind=body.kind,
        ip=deps.client_ip(request),
    )
    _etag(response, row.version)
    return _list(row)


@router.get("/lists/{list_id}")
async def get_list(
    list_id: uuid.UUID, session: SessionDep, request: Request, response: Response
) -> ListWithItems:
    row, items = await service.get_list(deps.database(request), session, list_id)
    _etag(response, row.version)
    return ListWithItems(**_list(row).model_dump(), items=[_item(i) for i in items])


@router.patch("/lists/{list_id}")
async def update_list(
    list_id: uuid.UUID,
    body: ListPatch,
    session: SessionDep,
    request: Request,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> ListOut:
    try:
        row = await service.update_list(
            deps.database(request),
            session,
            list_id,
            expected_version=_version(if_match),
            title=body.title,
            kind=body.kind,
            ip=deps.client_ip(request),
        )
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    _etag(response, row.version)
    return _list(row)


@router.delete("/lists/{list_id}", status_code=204)
async def delete_list(list_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.delete_list(deps.database(request), session, list_id, deps.client_ip(request))


@router.post("/lists/{list_id}/items", status_code=201)
async def add_item(
    list_id: uuid.UUID,
    body: ItemIn,
    session: SessionDep,
    request: Request,
    response: Response,
    idempotency_key: IdemKey = None,
) -> ItemOut:
    row = await service.add_item(
        deps.database(request),
        session,
        list_id,
        text=body.text,
        quantity=body.quantity,
        unit=body.unit,
        price_cents=body.price_cents,
        idempotency_key=idempotency_key,
        ip=deps.client_ip(request),
    )
    _etag(response, row.version)
    return _item(row)


@router.patch("/list-items/{item_id}")
async def update_item(
    item_id: uuid.UUID,
    body: ItemPatch,
    session: SessionDep,
    request: Request,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> ItemOut:
    fields = body.model_dump(include=body.model_fields_set)
    only_check = set(fields) <= {"checked"}
    version = None if (only_check and not if_match) else _version(if_match)
    try:
        row = await service.update_item(
            deps.database(request),
            session,
            item_id,
            expected_version=version,
            fields=fields,
            ip=deps.client_ip(request),
        )
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    _etag(response, row.version)
    return _item(row)


@router.delete("/list-items/{item_id}", status_code=204)
async def delete_item(item_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.delete_item(deps.database(request), session, item_id, deps.client_ip(request))
