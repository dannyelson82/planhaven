"""Contacts (contractors, suppliers) and their sharing; quotes and costs on projects."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.api.projects import _etag, _version
from app.api.sharing import AddMember, MemberOut, RoleChange
from app.services import contacts as service
from app.services import costs as cost_service
from app.services import sharing as sharing_service
from app.services.costs import LinkError
from app.services.projects import ConflictError
from app.services.sharing import SharingError

router = APIRouter(prefix="/api/v1", tags=["contacts"])

MAX_CENTS = 100_000_000_000


class ContactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=200)]
    company: Annotated[str, Field(max_length=200)] = ""
    kind: Literal["contractor", "supplier", "other"] = "contractor"
    phone: Annotated[str, Field(max_length=50)] = ""
    email: Annotated[str, Field(max_length=254)] = ""
    website: Annotated[str, Field(max_length=500, pattern=r"^(https?://\S*)?$")] = ""
    notes: Annotated[str, Field(max_length=20000)] = ""


class QuoteOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_title: str
    title: str
    amount_cents: int | None
    status: str
    notes: str
    contact_id: uuid.UUID | None
    contact_name: str | None
    attachment_id: uuid.UUID | None
    attachment_name: str | None
    updated_at: datetime
    version: int


class ContactOut(BaseModel):
    id: uuid.UUID
    name: str
    company: str
    kind: str
    phone: str
    email: str
    website: str
    notes: str
    role: str | None
    updated_at: datetime
    version: int
    quotes: list[QuoteOut] | None = None


class QuoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, Field(min_length=1, max_length=200)]
    contact_id: uuid.UUID | None = None
    amount_cents: Annotated[int, Field(ge=0, le=MAX_CENTS)] | None = None
    status: Literal["requested", "received", "accepted", "declined"] = "requested"
    attachment_id: uuid.UUID | None = None
    notes: Annotated[str, Field(max_length=20000)] = ""


class QuoteChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    contact_id: uuid.UUID | None = None
    amount_cents: Annotated[int, Field(ge=0, le=MAX_CENTS)] | None = None
    status: Literal["requested", "received", "accepted", "declined"] | None = None
    attachment_id: uuid.UUID | None = None
    notes: Annotated[str, Field(max_length=20000)] | None = None


class CostIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: Annotated[str, Field(min_length=1, max_length=300)]
    amount_cents: Annotated[int, Field(ge=-MAX_CENTS, le=MAX_CENTS)]
    spent_on: date | None = None
    quote_id: uuid.UUID | None = None


class CostOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    description: str
    amount_cents: int
    spent_on: date
    quote_id: uuid.UUID | None


def _contact(c: service.ContactRow, quotes: list[service.QuoteRow] | None = None) -> ContactOut:
    out = ContactOut.model_validate(c, from_attributes=True)
    if quotes is not None:
        out.quotes = [QuoteOut.model_validate(q, from_attributes=True) for q in quotes]
    return out


# ------------------------------------------------------------------ contacts


@router.get("/contacts")
async def list_contacts(session: SessionDep, request: Request) -> list[ContactOut]:
    return [_contact(c) for c in await service.list_contacts(deps.database(request), session)]


@router.post("/contacts", status_code=201)
async def create_contact(
    body: ContactIn, session: SessionDep, request: Request, response: Response
) -> ContactOut:
    contact = await service.create_contact(
        deps.database(request), session, body.model_dump(), deps.client_ip(request)
    )
    _etag(response, contact.version)
    return _contact(contact, [])


@router.get("/contacts/{contact_id}")
async def get_contact(
    contact_id: uuid.UUID, session: SessionDep, request: Request, response: Response
) -> ContactOut:
    contact, quotes = await service.get_contact(deps.database(request), session, contact_id)
    _etag(response, contact.version)
    return _contact(contact, quotes)


@router.put("/contacts/{contact_id}")
async def update_contact(
    contact_id: uuid.UUID,
    body: ContactIn,
    session: SessionDep,
    request: Request,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> ContactOut:
    try:
        contact = await service.update_contact(
            deps.database(request), session, contact_id, _version(if_match), body.model_dump()
        )
    except ConflictError:
        raise HTTPException(
            409, "Someone else changed this contact. Reload and try again."
        ) from None
    _etag(response, contact.version)
    return _contact(contact)


@router.delete("/contacts/{contact_id}", status_code=204)
async def delete_contact(contact_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.delete_contact(
        deps.database(request), session, contact_id, deps.client_ip(request)
    )


@router.get("/contacts/{contact_id}/members")
async def list_members(
    contact_id: uuid.UUID, session: SessionDep, request: Request
) -> list[MemberOut]:
    rows = await sharing_service.list_members(
        deps.database(request), session, contact_id, "contact"
    )
    return [
        MemberOut(user_id=r.user_id, display_name=r.display_name, email=r.email, role=r.role)
        for r in rows
    ]


@router.post("/contacts/{contact_id}/members", status_code=201)
async def add_member(
    contact_id: uuid.UUID, body: AddMember, session: SessionDep, request: Request
) -> None:
    try:
        await sharing_service.add_member(
            deps.database(request),
            session,
            contact_id,
            body.user_id,
            body.role,
            deps.client_ip(request),
            "contact",
        )
    except SharingError as exc:
        raise HTTPException(409, str(exc)) from None


@router.patch("/contacts/{contact_id}/members/{user_id}", status_code=204)
async def change_role(
    contact_id: uuid.UUID,
    user_id: uuid.UUID,
    body: RoleChange,
    session: SessionDep,
    request: Request,
) -> None:
    try:
        await sharing_service.change_role(
            deps.database(request),
            session,
            contact_id,
            user_id,
            body.role,
            deps.client_ip(request),
            "contact",
        )
    except SharingError as exc:
        raise HTTPException(409, str(exc)) from None


@router.delete("/contacts/{contact_id}/members/{user_id}", status_code=204)
async def remove_member(
    contact_id: uuid.UUID, user_id: uuid.UUID, session: SessionDep, request: Request
) -> None:
    try:
        await sharing_service.remove_member(
            deps.database(request), session, contact_id, user_id, deps.client_ip(request), "contact"
        )
    except SharingError as exc:
        raise HTTPException(409, str(exc)) from None


# ------------------------------------------------------------------ quotes and costs


@router.get("/projects/{project_id}/quotes")
async def list_quotes(
    project_id: uuid.UUID, session: SessionDep, request: Request
) -> list[QuoteOut]:
    rows = await cost_service.quotes_for_project(deps.database(request), session, project_id)
    return [QuoteOut.model_validate(q, from_attributes=True) for q in rows]


@router.post("/projects/{project_id}/quotes", status_code=201)
async def create_quote(
    project_id: uuid.UUID, body: QuoteIn, session: SessionDep, request: Request, response: Response
) -> QuoteOut:
    try:
        quote = await cost_service.create_quote(
            deps.database(request), session, project_id, body.model_dump(), deps.client_ip(request)
        )
    except LinkError as exc:
        raise HTTPException(422, str(exc)) from None
    _etag(response, quote.version)
    return QuoteOut.model_validate(quote, from_attributes=True)


@router.patch("/quotes/{quote_id}")
async def update_quote(
    quote_id: uuid.UUID,
    body: QuoteChange,
    session: SessionDep,
    request: Request,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> QuoteOut:
    try:
        quote = await cost_service.update_quote(
            deps.database(request),
            session,
            quote_id,
            _version(if_match),
            body.model_dump(exclude_unset=True),
        )
    except ConflictError:
        raise HTTPException(409, "Someone else changed this quote. Reload and try again.") from None
    except LinkError as exc:
        raise HTTPException(422, str(exc)) from None
    _etag(response, quote.version)
    return QuoteOut.model_validate(quote, from_attributes=True)


@router.delete("/quotes/{quote_id}", status_code=204)
async def delete_quote(quote_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await cost_service.delete_quote(
        deps.database(request), session, quote_id, deps.client_ip(request)
    )


@router.get("/projects/{project_id}/costs")
async def list_costs(project_id: uuid.UUID, session: SessionDep, request: Request) -> list[CostOut]:
    rows = await cost_service.costs_for_project(deps.database(request), session, project_id)
    return [CostOut.model_validate(c, from_attributes=True) for c in rows]


@router.post("/projects/{project_id}/costs", status_code=201)
async def create_cost(
    project_id: uuid.UUID, body: CostIn, session: SessionDep, request: Request
) -> CostOut:
    values = body.model_dump()  # no date: the database uses today
    try:
        cost = await cost_service.create_cost(
            deps.database(request), session, project_id, values, deps.client_ip(request)
        )
    except LinkError as exc:
        raise HTTPException(422, str(exc)) from None
    return CostOut.model_validate(cost, from_attributes=True)


@router.delete("/costs/{cost_id}", status_code=204)
async def delete_cost(cost_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await cost_service.delete_cost(
        deps.database(request), session, cost_id, deps.client_ip(request)
    )
