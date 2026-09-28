"""Notes: REST for metadata, WebSocket for real-time co-editing, and a live-updates socket
per project (ADR 0011, SECURITY.md §7.15)."""

import asyncio
import contextlib
import json
import time
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response, WebSocket
from fastapi.websockets import WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

from app import authz
from app.api import deps
from app.api.deps import SessionDep
from app.api.projects import _etag, _version
from app.core import security_log
from app.services import live
from app.services import notes as service
from app.services.auth import CurrentSession
from app.services.notes import CollabCloseError, Peer, rooms
from app.services.projects import ConflictError

router = APIRouter(prefix="/api/v1")

Title = Annotated[str, Field(min_length=1, max_length=200)]


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title


class TextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Annotated[str, Field(max_length=service.MAX_TEXT_CONTENT)]


class NoteOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    text_content: str
    source: str
    updated_at: datetime
    version: int
    can_edit: bool = False


def _note(n: service.NoteRow, can_edit: bool = False) -> NoteOut:
    return NoteOut(
        id=n.id,
        project_id=n.project_id,
        title=n.title,
        text_content=n.text_content,
        source=n.source,
        updated_at=n.updated_at,
        version=n.version,
        can_edit=can_edit,
    )


@router.get("/projects/{project_id}/notes")
async def list_notes(project_id: uuid.UUID, session: SessionDep, request: Request) -> list[NoteOut]:
    rows = await service.notes_for_project(deps.database(request), session, project_id)
    return [_note(n) for n in rows]


@router.post("/projects/{project_id}/notes", status_code=201)
async def create_note(
    project_id: uuid.UUID, body: NoteIn, session: SessionDep, request: Request, response: Response
) -> NoteOut:
    note = await service.create_note(
        deps.database(request), session, project_id, body.title, deps.client_ip(request)
    )
    _etag(response, note.version)
    return _note(note, can_edit=True)


@router.get("/notes/{note_id}")
async def get_note(
    note_id: uuid.UUID, session: SessionDep, request: Request, response: Response
) -> NoteOut:
    note, can_edit = await service.get_note(deps.database(request), session, note_id)
    _etag(response, note.version)
    return _note(note, can_edit)


@router.patch("/notes/{note_id}")
async def rename_note(
    note_id: uuid.UUID,
    body: NoteIn,
    session: SessionDep,
    request: Request,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> NoteOut:
    try:
        note = await service.rename(
            deps.database(request),
            session,
            note_id,
            _version(if_match),
            body.title,
            deps.client_ip(request),
        )
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    _etag(response, note.version)
    return _note(note, can_edit=True)


@router.put("/notes/{note_id}/text", status_code=204)
async def set_note_text(
    note_id: uuid.UUID, body: TextIn, session: SessionDep, request: Request
) -> None:
    await service.set_text(deps.database(request), session, note_id, body.text)


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(note_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.delete_note(deps.database(request), session, note_id, deps.client_ip(request))


async def _safe_close(websocket: WebSocket, code: int, reason: str) -> None:
    with contextlib.suppress(Exception):
        await websocket.close(code=code, reason=reason)


@router.websocket("/collab/notes/{note_id}")
async def collaborate(websocket: WebSocket, note_id: uuid.UUID) -> None:
    session = await deps.websocket_session(websocket)
    if session is None:
        await websocket.close(code=4401)
        return
    db = websocket.app.state.db
    try:
        note, can_write = await service.get_note(db, session, note_id)
    except authz.AuthzError:
        await websocket.close(code=4404)
        return
    if not live.claim_socket(session.user.id):
        await websocket.close(code=4429)
        return
    try:
        await _collaborate(websocket, session, note, can_write)
    finally:
        live.release_socket(session.user.id)


async def _collaborate(
    websocket: WebSocket, session: CurrentSession, note: service.NoteRow, can_write: bool
) -> None:
    db = websocket.app.state.db
    await websocket.accept()
    peer = Peer(
        send=websocket.send_bytes,
        user_id=session.user.id,
        can_write=can_write,
        close=lambda code, reason: _safe_close(websocket, code, reason),
    )
    room = await rooms.join(db, session.user.id, note, peer)
    last_check = time.monotonic()
    try:
        for message in service.opening_messages(room):
            await websocket.send_bytes(message)
        while True:
            remaining = max(0.1, service.RECHECK_SECONDS - (time.monotonic() - last_check))
            try:
                frame = await asyncio.wait_for(websocket.receive(), remaining)
            except TimeoutError:
                frame = None
            if frame is not None:
                if frame["type"] == "websocket.disconnect":
                    break
                data = frame.get("bytes")
                if data is None:
                    raise CollabCloseError(4400, "binary frames only")
                await service.handle_message(db, room, peer, data)
            if time.monotonic() - last_check >= service.RECHECK_SECONDS:
                readable, peer.can_write = await service.still_allowed(db, session.token, note)
                if not readable:
                    raise CollabCloseError(4403, "access removed")
                last_check = time.monotonic()
    except CollabCloseError as exc:
        # Refusals (read-only, too big, too fast, malformed, access removed) are security
        # events; never with the update itself.
        security_log.event(
            "collab_refused",
            ip=None,
            user_id=session.user.id,
            note_id=str(note.id),
            code=exc.code,
            reason=exc.reason,
        )
        await _safe_close(websocket, exc.code, exc.reason)
    except WebSocketDisconnect:
        pass
    finally:
        rooms.leave(room, peer)


@router.websocket("/live/projects/{project_id}")
async def live_updates(websocket: WebSocket, project_id: uuid.UUID) -> None:
    """Tells an open project page what changed (kind only) so it can refresh."""
    session = await deps.websocket_session(websocket)
    if session is None:
        await websocket.close(code=4401)
        return
    db = websocket.app.state.db
    try:
        await service.notes_for_project(db, session, project_id)  # project view check
    except authz.AuthzError:
        await websocket.close(code=4404)
        return
    if not live.claim_socket(session.user.id):
        await websocket.close(code=4429)
        return
    try:
        await _live_updates(websocket, session, project_id)
    finally:
        live.release_socket(session.user.id)


async def _live_updates(
    websocket: WebSocket, session: CurrentSession, project_id: uuid.UUID
) -> None:
    db = websocket.app.state.db
    await websocket.accept()
    queue = live.subscribe(project_id)
    receiver = asyncio.ensure_future(websocket.receive())
    try:
        while True:
            getter = asyncio.ensure_future(queue.get())
            done, _ = await asyncio.wait(
                {getter, receiver},
                timeout=service.RECHECK_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if receiver in done:
                getter.cancel()
                break
            if getter in done:
                await websocket.send_text(json.dumps({"kind": getter.result()}))
            else:
                getter.cancel()
                try:
                    await service.notes_for_project(db, session, project_id)
                except authz.AuthzError:
                    await _safe_close(websocket, 4403, "access removed")
                    break
    except WebSocketDisconnect:
        pass
    finally:
        receiver.cancel()
        live.unsubscribe(project_id, queue)
