"""In-app notifications (SECURITY.md §7.12). Push delivery comes with Web Push (phase 0.3).
Notifications carry metadata only: never note bodies, codes or tokens."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.db import admin as store
from app.db.database import Database
from app.services.auth import CurrentSession


@dataclass(frozen=True, slots=True)
class Notification:
    id: uuid.UUID
    kind: str
    data: dict[str, Any]
    created_at: datetime
    read: bool


async def list_own(db: Database, session: CurrentSession) -> list[Notification]:
    async with db.user_transaction(session.user.id) as conn:
        rows = await store.own_notifications(conn, session.user.id)
    return [Notification(r.id, r.kind, r.data, r.created_at, r.read_at is not None) for r in rows]


async def mark_read(db: Database, session: CurrentSession, notification_id: uuid.UUID) -> bool:
    async with db.user_transaction(session.user.id) as conn:
        return await store.mark_read(conn, session.user.id, notification_id)
