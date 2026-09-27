"""Sharing projects with household members (ARCHITECTURE.md §7.5).

Members can see who else is on a project. Owners add, re-role and remove members, with a
fresh second factor; anyone may leave a project. A project always keeps an owner (enforced in
the database). People who are added get a notification.
"""

import uuid

from app import authz
from app.db import admin as notify_store
from app.db import auth as audit
from app.db import projects as project_store
from app.db import sharing as store
from app.db.database import Database
from app.services.auth import CurrentSession

ROLES = ("owner", "editor", "viewer")

Member = store.MemberRow
DirectoryEntry = store.DirectoryRow


class SharingError(Exception):
    """A sharing change that isn't allowed (message is safe to show)."""


async def _access(
    db: Database, session: CurrentSession, project_id: uuid.UUID
) -> authz.ProjectAccess:
    async with db.user_transaction(session.user.id) as conn:
        access = authz.ProjectAccess(await project_store.role(conn, project_id))
        if access.role is not None and await project_store.get_project(conn, project_id) is None:
            access = authz.ProjectAccess(None)  # deleted project
    return access


async def directory(db: Database, session: CurrentSession) -> list[store.DirectoryRow]:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.system_transaction() as conn:
        return await store.directory(conn, session.user.id)


async def list_members(
    db: Database, session: CurrentSession, project_id: uuid.UUID
) -> list[store.MemberRow]:
    authz.require(
        session.principal, authz.Action.PROJECT_VIEW, await _access(db, session, project_id)
    )
    async with db.system_transaction() as conn:
        return await store.members(conn, project_id)


async def add_member(
    db: Database,
    session: CurrentSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    ip: str | None,
) -> None:
    access = await _access(db, session, project_id)
    authz.require(session.principal, authz.Action.PROJECT_VIEW, access)
    authz.require(session.principal, authz.Action.PROJECT_SHARE, access)
    if role not in ROLES:
        raise SharingError("Unknown role.")
    async with db.system_transaction() as conn:
        if not await store.active_user_exists(conn, user_id):
            raise authz.NotFoundError("Not found.")
    async with db.user_transaction(session.user.id) as conn:
        if not await store.add_member(conn, project_id, user_id, role):
            raise SharingError("That person is already a member.")
        await project_store.emit(
            conn,
            "project.member_added",
            user_id=session.user.id,
            project_id=project_id,
            payload={"user_id": str(user_id), "role": role},
        )
        await audit.record_audit(
            conn,
            action="project.member_added",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=project_id,
            resource_type="user",
            resource_id=user_id,
        )
    async with db.system_transaction() as conn:
        project = await project_store.title(conn, project_id)
        await notify_store.notify(
            conn,
            user_id,
            "shared_with_you",
            {
                "project_id": str(project_id),
                "title": project,
                "role": role,
                "by": session.user.display_name,
            },
        )


async def change_role(
    db: Database,
    session: CurrentSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    ip: str | None,
) -> None:
    access = await _access(db, session, project_id)
    authz.require(session.principal, authz.Action.PROJECT_VIEW, access)
    authz.require(session.principal, authz.Action.PROJECT_SHARE, access)
    if role not in ROLES:
        raise SharingError("Unknown role.")
    try:
        async with db.user_transaction(session.user.id) as conn:
            if not await store.set_role(conn, project_id, user_id, role):
                raise authz.NotFoundError("Not found.")
            await audit.record_audit(
                conn,
                action="project.member_role_changed",
                actor_user_id=session.user.id,
                ip=ip,
                project_id=project_id,
                resource_type="user",
                resource_id=user_id,
            )
    except Exception as exc:
        if "at least one owner" in str(exc):
            raise SharingError("A project must keep at least one owner.") from None
        raise


async def remove_member(
    db: Database,
    session: CurrentSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    ip: str | None,
) -> None:
    """Owners remove anyone; everyone else may only remove themselves (leave)."""
    access = await _access(db, session, project_id)
    authz.require(session.principal, authz.Action.PROJECT_VIEW, access)
    if user_id != session.user.id:
        authz.require(session.principal, authz.Action.PROJECT_SHARE, access)
    try:
        async with db.user_transaction(session.user.id) as conn:
            if not await store.remove(conn, project_id, user_id):
                raise authz.NotFoundError("Not found.")
            await audit.record_audit(
                conn,
                action="project.member_removed" if user_id != session.user.id else "project.left",
                actor_user_id=session.user.id,
                ip=ip,
                project_id=project_id,
                resource_type="user",
                resource_id=user_id,
            )
    except Exception as exc:
        if "at least one owner" in str(exc):
            raise SharingError("A project must keep at least one owner.") from None
        raise
