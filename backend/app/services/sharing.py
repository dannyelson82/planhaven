"""Sharing projects and assets with household members (ARCHITECTURE.md §7.5, ADR 0005).

Members can see who else is on a project or asset. Owners add, re-role and remove members,
with a fresh second factor; anyone may leave. Each keeps at least one owner (enforced in the
database). People who are added get a notification.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from app import authz
from app.db import admin as notify_store
from app.db import assets as asset_store
from app.db import auth as audit
from app.db import contacts as contact_store
from app.db import projects as project_store
from app.db import sharing as store
from app.db.database import Database
from app.services.auth import CurrentSession

ROLES = ("owner", "editor", "viewer")

Member = store.MemberRow
DirectoryEntry = store.DirectoryRow
Kind = Literal["project", "asset", "contact"]


@dataclass(frozen=True, slots=True)
class _Actions:
    view: authz.Action
    share: authz.Action


_ACTIONS: dict[str, _Actions] = {
    "project": _Actions(authz.Action.PROJECT_VIEW, authz.Action.PROJECT_SHARE),
    "asset": _Actions(authz.Action.ASSET_VIEW, authz.Action.ASSET_SHARE),
    "contact": _Actions(authz.Action.CONTACT_VIEW, authz.Action.CONTACT_SHARE),
}


class SharingError(Exception):
    """A sharing change that isn't allowed (message is safe to show)."""


async def _access(
    db: Database, session: CurrentSession, resource_id: uuid.UUID, kind: Kind
) -> authz.ProjectAccess:
    async with db.user_transaction(session.user.id) as conn:
        if kind == "project":
            access = authz.ProjectAccess(await project_store.role(conn, resource_id))
            exists = await project_store.get_project(conn, resource_id) is not None
        elif kind == "asset":
            access = authz.ProjectAccess(await asset_store.role(conn, resource_id))
            exists = await asset_store.get_asset(conn, resource_id) is not None
        else:
            access = authz.ProjectAccess(await contact_store.role(conn, resource_id))
            exists = await contact_store.get_contact(conn, resource_id) is not None
    return access if exists else authz.ProjectAccess(None)  # deleted


async def directory(db: Database, session: CurrentSession) -> list[store.DirectoryRow]:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.system_transaction() as conn:
        return await store.directory(conn, session.user.id)


async def list_members(
    db: Database, session: CurrentSession, resource_id: uuid.UUID, kind: Kind = "project"
) -> list[store.MemberRow]:
    access = await _access(db, session, resource_id, kind)
    authz.require(session.principal, _ACTIONS[kind].view, access)
    async with db.system_transaction() as conn:
        return await store.members(conn, resource_id, kind)


async def _notify_added(
    db: Database,
    session: CurrentSession,
    resource_id: uuid.UUID,
    kind: Kind,
    user_id: uuid.UUID,
    role: str,
) -> None:
    async with db.system_transaction() as conn:
        if kind == "project":
            title = await project_store.title(conn, resource_id)
            payload = {"project_id": str(resource_id), "title": title}
            event = "shared_with_you"
        elif kind == "asset":
            asset = await asset_store.get_asset(conn, resource_id)
            payload = {"asset_id": str(resource_id), "title": asset.name if asset else ""}
            event = "asset_shared_with_you"
        else:
            contact = await contact_store.get_contact(conn, resource_id)
            payload = {"contact_id": str(resource_id), "title": contact.name if contact else ""}
            event = "contact_shared_with_you"
        await notify_store.notify(
            conn, user_id, event, {**payload, "role": role, "by": session.user.display_name}
        )


async def add_member(
    db: Database,
    session: CurrentSession,
    resource_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    ip: str | None,
    kind: Kind = "project",
) -> None:
    access = await _access(db, session, resource_id, kind)
    authz.require(session.principal, _ACTIONS[kind].view, access)
    authz.require(session.principal, _ACTIONS[kind].share, access)
    if role not in ROLES:
        raise SharingError("Unknown role.")
    async with db.system_transaction() as conn:
        if not await store.active_user_exists(conn, user_id):
            raise authz.NotFoundError("Not found.")
    async with db.user_transaction(session.user.id) as conn:
        if not await store.add_member(conn, resource_id, user_id, role, kind):
            raise SharingError("That person is already a member.")
        if kind == "project":
            await project_store.emit(
                conn,
                "project.member_added",
                user_id=session.user.id,
                project_id=resource_id,
                payload={"user_id": str(user_id), "role": role},
            )
        await audit.record_audit(
            conn,
            action=f"{kind}.member_added",
            actor_user_id=session.user.id,
            ip=ip,
            **_where(kind, resource_id),
            resource_type="user",
            resource_id=user_id,
        )
    await _notify_added(db, session, resource_id, kind, user_id, role)


def _where(kind: Kind, resource_id: uuid.UUID) -> dict[str, Any]:
    """Audit fields naming the project, or the asset (in details)."""
    if kind == "project":
        return {"project_id": resource_id}
    return {"details": json.dumps({f"{kind}_id": str(resource_id)})}


def _owner_rule(exc: Exception, kind: Kind) -> None:
    if "at least one owner" in str(exc):
        raise SharingError(f"A {kind} must keep at least one owner.") from None


async def change_role(
    db: Database,
    session: CurrentSession,
    resource_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    ip: str | None,
    kind: Kind = "project",
) -> None:
    access = await _access(db, session, resource_id, kind)
    authz.require(session.principal, _ACTIONS[kind].view, access)
    authz.require(session.principal, _ACTIONS[kind].share, access)
    if role not in ROLES:
        raise SharingError("Unknown role.")
    try:
        async with db.user_transaction(session.user.id) as conn:
            if not await store.set_role(conn, resource_id, user_id, role, kind):
                raise authz.NotFoundError("Not found.")
            await audit.record_audit(
                conn,
                action=f"{kind}.member_role_changed",
                actor_user_id=session.user.id,
                ip=ip,
                **_where(kind, resource_id),
                resource_type="user",
                resource_id=user_id,
            )
    except Exception as exc:
        _owner_rule(exc, kind)
        raise


async def remove_member(
    db: Database,
    session: CurrentSession,
    resource_id: uuid.UUID,
    user_id: uuid.UUID,
    ip: str | None,
    kind: Kind = "project",
) -> None:
    """Owners remove anyone; everyone else may only remove themselves (leave)."""
    access = await _access(db, session, resource_id, kind)
    authz.require(session.principal, _ACTIONS[kind].view, access)
    if user_id != session.user.id:
        authz.require(session.principal, _ACTIONS[kind].share, access)
    try:
        async with db.user_transaction(session.user.id) as conn:
            if not await store.remove(conn, resource_id, user_id, kind):
                raise authz.NotFoundError("Not found.")
            await audit.record_audit(
                conn,
                action=f"{kind}.member_removed" if user_id != session.user.id else f"{kind}.left",
                actor_user_id=session.user.id,
                ip=ip,
                **_where(kind, resource_id),
                resource_type="user",
                resource_id=user_id,
            )
    except Exception as exc:
        _owner_rule(exc, kind)
        raise
