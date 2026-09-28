"""Contacts (contractors, suppliers) and their sharing; quotes and costs on projects."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api import deps
from app.api.attachments import _file
from app.api.deps import SessionDep
from app.api.projects import _etag, _version
from app.api.sharing import AddMember, MemberOut, RoleChange
from app.core.http import FILE_CSP
from app.services import attachments as attachment_service
from app.services import contacts as service
from app.services import costs as cost_service
from app.services import sharing as sharing_service
from app.services import vcard
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
    has_photo: bool = False
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
    store: str = ""
    receipt_id: uuid.UUID | None = None
    receipt_name: str | None = None
    item_count: int = 0
    version: int = 1


class CostChange(BaseModel):
    """Only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")
    description: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    amount_cents: Annotated[int, Field(ge=-MAX_CENTS, le=MAX_CENTS)] | None = None
    spent_on: date | None = None
    quote_id: uuid.UUID | None = None
    store: Annotated[str, Field(max_length=200)] | None = None
    receipt_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _required_stay_set(self) -> CostChange:
        for name in ("description", "amount_cents", "spent_on", "store"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} can't be empty.")
        return self


Qty = Annotated[Decimal, Field(ge=0, le=Decimal("999999999"), max_digits=12, decimal_places=3)]
Price = Annotated[int, Field(ge=0, le=1_000_000_000_000)]


class CostItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Annotated[str, Field(min_length=1, max_length=500)]
    quantity: Qty | None = None
    price_cents: Price | None = None


class CostItemsIn(BaseModel):
    """Typed items and/or list items (copied with their estimated prices)."""

    model_config = ConfigDict(extra="forbid")
    items: Annotated[list[CostItemIn], Field(max_length=200)] = []
    list_item_ids: Annotated[list[uuid.UUID], Field(max_length=200)] = []


class CostItemChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    quantity: Qty | None = None
    price_cents: Price | None = None

    @model_validator(mode="after")
    def _text_stays_set(self) -> CostItemChange:
        if "text" in self.model_fields_set and self.text is None:
            raise ValueError("text can't be empty.")
        return self


class CostItemOut(BaseModel):
    id: uuid.UUID
    cost_id: uuid.UUID
    text: str
    quantity: Decimal | None
    price_cents: int | None
    list_item_id: uuid.UUID | None
    version: int


class PurchaseOut(CostOut):
    items: list[CostItemOut]
    can_edit: bool


def _contact(c: service.ContactRow, quotes: list[service.QuoteRow] | None = None) -> ContactOut:
    out = ContactOut.model_validate(c, from_attributes=True)
    out.has_photo = c.photo_sha256 is not None
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


@router.post("/contacts/import", status_code=201)
async def import_contact(
    session: SessionDep,
    request: Request,
    kind: Literal["contractor", "supplier", "other"] = "contractor",
) -> ContactOut:
    """A new contact from a contact card (.vcf) shared from a phone; the file is the raw body."""
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > vcard.MAX_BYTES:
            raise HTTPException(413, "This contact card is too large.")
    try:
        contact = await service.import_card(
            deps.database(request),
            deps.blobs(request),
            session,
            bytes(data),
            kind=kind,
            max_photo_bytes=vcard.MAX_PHOTO_BYTES,
            ip=deps.client_ip(request),
        )
    except vcard.VCardError as exc:
        raise HTTPException(422, str(exc)) from None
    return _contact(contact)


@router.get("/contacts/{contact_id}/vcard")
async def export_contact(contact_id: uuid.UUID, session: SessionDep, request: Request) -> Response:
    """The contact as a card (.vcf) to save to a phone."""
    name, text = await service.export_card(
        deps.database(request), deps.blobs(request), session, contact_id
    )
    ascii_name = name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
    return Response(
        content=text,
        media_type="text/vcard; charset=utf-8",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
            ),
            "Content-Security-Policy": FILE_CSP,
            "Cache-Control": "private, no-store",
        },
    )


@router.put("/contacts/{contact_id}/photo")
async def set_photo(contact_id: uuid.UUID, session: SessionDep, request: Request) -> ContactOut:
    """The photo is the raw request body, like attachments."""
    try:
        contact = await service.set_photo(
            deps.database(request),
            deps.blobs(request),
            session,
            contact_id,
            chunks=request.stream(),
            max_bytes=deps.settings(request).max_upload_mb * 1024 * 1024,
            ip=deps.client_ip(request),
        )
    except attachment_service.UploadTooLargeError:
        raise HTTPException(413, "This file is larger than the upload limit.") from None
    except attachment_service.UnsupportedFileError as exc:
        raise HTTPException(415, str(exc)) from None
    return _contact(contact)


@router.delete("/contacts/{contact_id}/photo", status_code=204)
async def remove_photo(contact_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.remove_photo(deps.database(request), session, contact_id)


@router.get("/contacts/{contact_id}/photo")
async def photo(contact_id: uuid.UUID, session: SessionDep, request: Request) -> FileResponse:
    sha, content_type = await service.photo(
        deps.database(request), session, contact_id, thumbnail=False
    )
    return _file(request, sha, content_type, "inline", "photo")


@router.get("/contacts/{contact_id}/photo/thumbnail")
async def photo_thumbnail(
    contact_id: uuid.UUID, session: SessionDep, request: Request
) -> FileResponse:
    sha, content_type = await service.photo(
        deps.database(request), session, contact_id, thumbnail=True
    )
    return _file(request, sha, content_type, "inline", "thumbnail.webp")


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
    return [_cost(c) for c in rows]


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
    return _cost(cost)


@router.delete("/costs/{cost_id}", status_code=204)
async def delete_cost(cost_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await cost_service.delete_cost(
        deps.database(request), session, cost_id, deps.client_ip(request)
    )


# ------------------------------------------------------------------ purchases (a cost's details)


def _cost(c: cost_service.CostRow) -> CostOut:
    return CostOut.model_validate(c, from_attributes=True)


def _items(rows: list[cost_service.CostItemRow]) -> list[CostItemOut]:
    return [CostItemOut.model_validate(i, from_attributes=True) for i in rows]


@router.get("/costs/{cost_id}")
async def get_purchase(
    cost_id: uuid.UUID, session: SessionDep, request: Request, response: Response
) -> PurchaseOut:
    cost, items, can_edit = await cost_service.get_purchase(
        deps.database(request), session, cost_id
    )
    _etag(response, cost.version)
    return PurchaseOut(**_cost(cost).model_dump(), items=_items(items), can_edit=can_edit)


@router.patch("/costs/{cost_id}")
async def update_cost(
    cost_id: uuid.UUID,
    body: CostChange,
    session: SessionDep,
    request: Request,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> CostOut:
    try:
        cost = await cost_service.update_cost(
            deps.database(request),
            session,
            cost_id,
            _version(if_match),
            body.model_dump(exclude_unset=True),
            deps.client_ip(request),
        )
    except ConflictError:
        raise HTTPException(409, "Someone else changed this entry. Reload and try again.") from None
    except LinkError as exc:
        raise HTTPException(422, str(exc)) from None
    _etag(response, cost.version)
    return _cost(cost)


@router.post("/costs/{cost_id}/items", status_code=201)
async def add_cost_items(
    cost_id: uuid.UUID, body: CostItemsIn, session: SessionDep, request: Request
) -> list[CostItemOut]:
    try:
        rows = await cost_service.add_items(
            deps.database(request),
            session,
            cost_id,
            items=[(i.text, i.quantity, i.price_cents) for i in body.items],
            list_item_ids=body.list_item_ids,
        )
    except cost_service.TooManyItemsError as exc:
        raise HTTPException(422, str(exc)) from None
    return _items(rows)


@router.patch("/cost-items/{item_id}")
async def update_cost_item(
    item_id: uuid.UUID,
    body: CostItemChange,
    session: SessionDep,
    request: Request,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> CostItemOut:
    try:
        item = await cost_service.update_item(
            deps.database(request),
            session,
            item_id,
            _version(if_match),
            body.model_dump(exclude_unset=True),
        )
    except ConflictError:
        raise HTTPException(409, "Someone else changed this item. Reload and try again.") from None
    _etag(response, item.version)
    return CostItemOut.model_validate(item, from_attributes=True)


@router.delete("/cost-items/{item_id}", status_code=204)
async def delete_cost_item(item_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await cost_service.delete_item(deps.database(request), session, item_id)
