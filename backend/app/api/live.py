"""Live updates for an open project page (ADR 0011): the server says only what kind of thing
changed ("tasks", "notes", ...) and the page refetches it through the normal API."""

import asyncio
import contextlib
import json
import uuid

from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketDisconnect

from app import authz
from app.api import deps
from app.services import live
from app.services import projects as project_service
from app.services.auth import CurrentSession

router = APIRouter(prefix="/api/v1")

RECHECK_SECONDS = 15.0


async def _safe_close(websocket: WebSocket, code: int, reason: str) -> None:
    with contextlib.suppress(Exception):
        await websocket.close(code=code, reason=reason)


async def _can_view(websocket: WebSocket, session: CurrentSession, project_id: uuid.UUID) -> bool:
    try:
        await project_service.get_project(websocket.app.state.db, session, project_id)
    except authz.AuthzError:
        return False
    return True


@router.websocket("/live/projects/{project_id}")
async def live_updates(websocket: WebSocket, project_id: uuid.UUID) -> None:
    session = await deps.websocket_session(websocket)
    if session is None:
        await websocket.close(code=4401)
        return
    if not await _can_view(websocket, session, project_id):
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
    await websocket.accept()
    queue = live.subscribe(project_id)
    receiver = asyncio.ensure_future(websocket.receive())
    loop = asyncio.get_running_loop()
    recheck_at = loop.time() + RECHECK_SECONDS
    try:
        while True:
            getter = asyncio.ensure_future(queue.get())
            done, _ = await asyncio.wait(
                {getter, receiver},
                timeout=max(0.0, recheck_at - loop.time()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if receiver in done:
                getter.cancel()
                break
            if getter in done:
                await websocket.send_text(json.dumps({"kind": getter.result()}))
            else:
                getter.cancel()
            # Still allowed to see this project? (Membership may have been removed.) Checked on
            # time even when changes keep arriving.
            if loop.time() >= recheck_at:
                if not await _can_view(websocket, session, project_id):
                    await _safe_close(websocket, 4403, "access removed")
                    break
                recheck_at = loop.time() + RECHECK_SECONDS
    except WebSocketDisconnect:
        pass
    finally:
        receiver.cancel()
        live.unsubscribe(project_id, queue)


@router.websocket("/live/me")
async def live_me(websocket: WebSocket) -> None:
    """The signed-in person's own channel: new messages and notifications, and being online."""
    session = await deps.websocket_session(websocket)
    if session is None:
        await websocket.close(code=4401)
        return
    if not live.claim_socket(session.user.id):
        await websocket.close(code=4429)
        return
    try:
        await _live_me(websocket, session)
    finally:
        live.release_socket(session.user.id)


async def _live_me(websocket: WebSocket, session: CurrentSession) -> None:
    await websocket.accept()
    queue = live.subscribe_person(session.user.id)
    receiver = asyncio.ensure_future(websocket.receive())
    loop = asyncio.get_running_loop()
    recheck_at = loop.time() + RECHECK_SECONDS
    try:
        while True:
            getter = asyncio.ensure_future(queue.get())
            done, _ = await asyncio.wait(
                {getter, receiver},
                timeout=max(0.0, recheck_at - loop.time()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if receiver in done:
                getter.cancel()
                break
            if getter in done:
                await websocket.send_text(json.dumps({"kind": getter.result()}))
            else:
                getter.cancel()
            # Still signed in? (Sign-out elsewhere, session expiry, account disabled.)
            if loop.time() >= recheck_at:
                if not await deps.session_still_valid(websocket, session):
                    await _safe_close(websocket, 4401, "signed out")
                    break
                recheck_at = loop.time() + RECHECK_SECONDS
    except WebSocketDisconnect:
        pass
    finally:
        receiver.cancel()
        live.unsubscribe_person(session.user.id, queue)
