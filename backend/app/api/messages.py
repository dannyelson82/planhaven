"""Messages between people, and the people list with online status (ADR 0018)."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.services import messages as service

router = APIRouter(prefix="/api/v1")

Title = Annotated[str, Field(min_length=1, max_length=100)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PersonOut(BaseModel):
    id: uuid.UUID
    name: str
    online: bool
    last_seen: datetime | None


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    is_group: bool
    members: list[PersonOut]
    unread: int
    last_message_at: datetime | None
    last_preview: str
    last_from_me: bool


class MessageOut(BaseModel):
    id: uuid.UUID
    sender_id: uuid.UUID
    sender_name: str
    body: str
    created_at: datetime
    deleted: bool
    mine: bool


class StartIn(Strict):
    people: Annotated[list[uuid.UUID], Field(min_length=1, max_length=49)]
    title: Title | None = None


class SendIn(Strict):
    body: Annotated[str, Field(min_length=1, max_length=service.MAX_BODY)]


class RenameIn(Strict):
    title: Title


class AddIn(Strict):
    user_id: uuid.UUID


class PresenceIO(Strict):
    hidden: bool


def _bad(exc: service.MessageError) -> HTTPException:
    return HTTPException(422, str(exc))


def _conversation(c: service.Conversation) -> ConversationOut:
    return ConversationOut.model_validate(c, from_attributes=True)


@router.get("/people/status")
async def people(session: SessionDep, request: Request) -> list[PersonOut]:
    rows = await service.people(deps.database(request), session)
    return [PersonOut.model_validate(p, from_attributes=True) for p in rows]


@router.get("/presence")
async def get_presence(session: SessionDep, request: Request) -> PresenceIO:
    return PresenceIO(hidden=await service.get_hidden(deps.database(request), session))


@router.put("/presence")
async def put_presence(body: PresenceIO, session: SessionDep, request: Request) -> PresenceIO:
    await service.set_hidden(deps.database(request), session, body.hidden)
    return body


@router.get("/conversations")
async def conversations(session: SessionDep, request: Request) -> list[ConversationOut]:
    rows = await service.conversations(deps.database(request), session)
    return [_conversation(c) for c in rows]


@router.post("/conversations", status_code=201)
async def start(body: StartIn, session: SessionDep, request: Request) -> ConversationOut:
    try:
        c = await service.start(
            deps.database(request),
            session,
            people_ids=body.people,
            title=body.title,
            ip=deps.client_ip(request),
        )
    except service.MessageError as exc:
        raise _bad(exc) from None
    return _conversation(c)


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, session: SessionDep, request: Request
) -> ConversationOut:
    found = await service.conversations(deps.database(request), session, conversation_id)
    if not found:
        raise HTTPException(404)
    return _conversation(found[0])


@router.patch("/conversations/{conversation_id}", status_code=204)
async def rename(
    conversation_id: uuid.UUID, body: RenameIn, session: SessionDep, request: Request
) -> None:
    try:
        await service.rename(deps.database(request), session, conversation_id, body.title)
    except service.MessageError as exc:
        raise _bad(exc) from None


@router.get("/conversations/{conversation_id}/messages")
async def messages(
    conversation_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    before: datetime | None = None,
) -> list[MessageOut]:
    rows = await service.messages(deps.database(request), session, conversation_id, before)
    return [MessageOut.model_validate(m, from_attributes=True) for m in rows]


@router.post("/conversations/{conversation_id}/messages", status_code=201)
async def send(
    conversation_id: uuid.UUID, body: SendIn, session: SessionDep, request: Request
) -> MessageOut:
    try:
        m = await service.send(
            deps.database(request), session, conversation_id, body.body, deps.client_ip(request)
        )
    except service.MessageError as exc:
        raise _bad(exc) from None
    return MessageOut.model_validate(m, from_attributes=True)


@router.post("/conversations/{conversation_id}/read", status_code=204)
async def mark_read(conversation_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.mark_read(deps.database(request), session, conversation_id)


@router.post("/conversations/{conversation_id}/leave", status_code=204)
async def leave(conversation_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    try:
        await service.leave(deps.database(request), session, conversation_id)
    except service.MessageError as exc:
        raise _bad(exc) from None


@router.post("/conversations/{conversation_id}/members", status_code=204)
async def add_member(
    conversation_id: uuid.UUID, body: AddIn, session: SessionDep, request: Request
) -> None:
    try:
        await service.add_member(deps.database(request), session, conversation_id, body.user_id)
    except service.MessageError as exc:
        raise _bad(exc) from None


@router.delete("/messages/{message_id}", status_code=204)
async def delete(message_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.delete(deps.database(request), session, message_id)
