"""The signed-in person's notifications, their notification settings and the devices that get
phone alerts (ADR 0018)."""

import uuid
from datetime import datetime, time
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.services import notifications as service

router = APIRouter(prefix="/api/v1")

Choice = Literal["push", "app", "off"]
Group = Literal["shared", "tasks", "service", "share_links", "security"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    data: dict[str, Any]
    title: str
    body: str
    url: str
    created_at: datetime
    read: bool


class UnreadOut(BaseModel):
    count: int


class SettingsIO(Strict):
    prefs: Annotated[dict[Group, Choice], Field(max_length=10)]
    quiet_from: time | None = None
    quiet_to: time | None = None
    time_zone: Annotated[str, Field(min_length=1, max_length=64)] = "UTC"
    previews: bool = True


class DeviceIn(Strict):
    endpoint: Annotated[str, Field(min_length=10, max_length=1000)]
    p256dh: Annotated[str, Field(min_length=10, max_length=200)]
    auth: Annotated[str, Field(min_length=10, max_length=100)]
    label: Annotated[str, Field(max_length=120)] = ""


class DeviceOut(BaseModel):
    id: uuid.UUID
    label: str
    created_at: datetime
    last_success_at: datetime | None


class ForgetIn(Strict):
    endpoint: Annotated[str, Field(min_length=10, max_length=1000)]


class KeyOut(BaseModel):
    public_key: str


def _bad(exc: service.SettingsError) -> HTTPException:
    return HTTPException(422, str(exc))


@router.get("/notifications")
async def list_notifications(session: SessionDep, request: Request) -> list[NotificationOut]:
    items = await service.list_own(deps.database(request), session)
    return [
        NotificationOut(
            id=n.id,
            kind=n.kind,
            data=n.data,
            title=n.text.title,
            body=n.text.body,
            url=n.text.url,
            created_at=n.created_at,
            read=n.read,
        )
        for n in items
    ]


@router.get("/notifications/unread")
async def unread(session: SessionDep, request: Request) -> UnreadOut:
    return UnreadOut(count=await service.unread(deps.database(request), session))


@router.post("/notifications/read-all", status_code=204)
async def mark_all_read(session: SessionDep, request: Request) -> None:
    await service.mark_all_read(deps.database(request), session)


@router.post("/notifications/{notification_id}/read", status_code=204)
async def mark_read(notification_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    if not await service.mark_read(deps.database(request), session, notification_id):
        raise HTTPException(404)


@router.get("/notification-settings")
async def get_settings(session: SessionDep, request: Request) -> SettingsIO:
    s = await service.get_settings(deps.database(request), session)
    return SettingsIO.model_validate(s, from_attributes=True)


@router.put("/notification-settings")
async def put_settings(body: SettingsIO, session: SessionDep, request: Request) -> SettingsIO:
    try:
        s = await service.put_settings(
            deps.database(request),
            session,
            prefs={str(k): str(v) for k, v in body.prefs.items()},
            quiet_from=body.quiet_from,
            quiet_to=body.quiet_to,
            time_zone=body.time_zone,
            previews=body.previews,
        )
    except service.SettingsError as exc:
        raise _bad(exc) from None
    return SettingsIO.model_validate(s, from_attributes=True)


@router.get("/push/key")
async def push_key(session: SessionDep, request: Request) -> KeyOut:
    """The server's public VAPID key, which the browser needs to subscribe."""
    path = Path(deps.settings(request).secrets_dir) / "vapid_public.txt"
    try:
        return KeyOut(public_key=path.read_text().strip())
    except OSError:
        raise HTTPException(503, "Phone alerts aren't set up on this server.") from None


@router.get("/push/devices")
async def list_devices(session: SessionDep, request: Request) -> list[DeviceOut]:
    rows = await service.devices(deps.database(request), session)
    return [DeviceOut.model_validate(d, from_attributes=True) for d in rows]


@router.post("/push/devices", status_code=201)
async def add_device(body: DeviceIn, session: SessionDep, request: Request) -> DeviceOut:
    try:
        device_id = await service.add_device(
            deps.database(request),
            session,
            endpoint=body.endpoint,
            p256dh=body.p256dh,
            auth=body.auth,
            label=body.label,
            ip=deps.client_ip(request),
        )
    except service.SettingsError as exc:
        raise _bad(exc) from None
    devices = await service.devices(deps.database(request), session)
    found = [d for d in devices if d.id == device_id]
    if not found:
        raise HTTPException(404)
    return DeviceOut.model_validate(found[0], from_attributes=True)


@router.delete("/push/devices/{device_id}", status_code=204)
async def remove_device(device_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    if not await service.remove_device(deps.database(request), session, device_id):
        raise HTTPException(404)


@router.post("/push/forget", status_code=204)
async def forget_this_browser(body: ForgetIn, session: SessionDep, request: Request) -> None:
    await service.forget_this_browser(deps.database(request), session, body.endpoint)


@router.post("/push/test", status_code=204)
async def send_test(session: SessionDep, request: Request) -> None:
    await service.send_test(deps.database(request), session, deps.client_ip(request))
