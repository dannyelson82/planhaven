"""Assets: vehicles, boats, houses and other things projects are about (ADR 0005).

An asset has a kind, a name, free-form details (label/value pairs such as VIN or engine) and
notes. Its linked projects are its service history. Sharing works like projects
(app.services.sharing with kind="asset").
"""

import uuid
from typing import Any

from app import authz
from app.db import assets as store
from app.db import auth as audit
from app.db import projects as project_store
from app.db.database import Database
from app.services import live
from app.services.auth import CurrentSession
from app.services.projects import ConflictError

AssetRow = store.AssetRow
LinkedProject = store.LinkedProject
KINDS = ("vehicle", "boat", "house", "property", "equipment", "tool", "other")


async def _access(conn: Any, asset_id: uuid.UUID) -> tuple[AssetRow, authz.ProjectAccess]:
    asset = await store.get_asset(conn, asset_id)
    if asset is None:
        raise authz.NotFoundError("Not found.")
    return asset, authz.ProjectAccess(asset.role)


async def list_assets(db: Database, session: CurrentSession) -> list[AssetRow]:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        return [a for a in await store.list_assets(conn) if a.role is not None]


async def get_asset(
    db: Database, session: CurrentSession, asset_id: uuid.UUID
) -> tuple[AssetRow, list[LinkedProject]]:
    async with db.user_transaction(session.user.id) as conn:
        asset, access = await _access(conn, asset_id)
        authz.require(session.principal, authz.Action.ASSET_VIEW, access)
        return asset, await store.linked_projects(conn, asset_id)


async def create_asset(
    db: Database,
    session: CurrentSession,
    *,
    name: str,
    kind: str,
    details: list[dict[str, str]],
    notes: str,
    ip: str | None,
) -> AssetRow:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        asset_id = await store.create_asset(
            conn, user_id=session.user.id, name=name, kind=kind, details=details, notes=notes
        )
        await audit.record_audit(
            conn,
            action="asset.created",
            actor_user_id=session.user.id,
            ip=ip,
            resource_type="asset",
            resource_id=asset_id,
        )
        asset = await store.get_asset(conn, asset_id)
    if asset is None:
        raise RuntimeError("created asset not visible")
    return asset


async def update_asset(
    db: Database,
    session: CurrentSession,
    asset_id: uuid.UUID,
    expected_version: int,
    *,
    name: str,
    kind: str,
    details: list[dict[str, str]],
    notes: str,
) -> AssetRow:
    async with db.user_transaction(session.user.id) as conn:
        _, access = await _access(conn, asset_id)
        authz.require(session.principal, authz.Action.ASSET_EDIT, access)
        version = await store.update_asset(
            conn, asset_id, expected_version, name=name, kind=kind, details=details, notes=notes
        )
        if version is None:
            raise ConflictError
        asset = await store.get_asset(conn, asset_id)
    if asset is None:
        raise authz.NotFoundError("Not found.")
    return asset


async def delete_asset(
    db: Database, session: CurrentSession, asset_id: uuid.UUID, ip: str | None
) -> None:
    async with db.user_transaction(session.user.id) as conn:
        _, access = await _access(conn, asset_id)
        authz.require(session.principal, authz.Action.ASSET_VIEW, access)
        authz.require(session.principal, authz.Action.ASSET_MANAGE, access)
        await store.delete_asset(conn, asset_id)
        await audit.record_audit(
            conn,
            action="asset.deleted",
            actor_user_id=session.user.id,
            ip=ip,
            resource_type="asset",
            resource_id=asset_id,
        )


async def link_project(
    db: Database,
    session: CurrentSession,
    project_id: uuid.UUID,
    asset_id: uuid.UUID | None,
) -> None:
    """Point a project at an asset (or at none). Needs edit rights on the project and at
    least view rights on the asset; the database checks the asset part again."""
    async with db.user_transaction(session.user.id) as conn:
        access = authz.ProjectAccess(await project_store.role(conn, project_id))
        if await project_store.get_project(conn, project_id) is None:
            access = authz.ProjectAccess(None)
        authz.require(session.principal, authz.Action.PROJECT_VIEW, access)
        authz.require(session.principal, authz.Action.PROJECT_EDIT, access)
        if asset_id is not None:
            _, asset_access = await _access(conn, asset_id)
            authz.require(session.principal, authz.Action.ASSET_VIEW, asset_access)
        await store.set_project_asset(conn, project_id, asset_id)
    live.publish(project_id, "project")
