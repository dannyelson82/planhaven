"""Folders for the projects list (ADR 0022): each person's own, nested up to 5 levels, one
folder per project. Folders only organize; they never change who can see a project."""

import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app import authz
from app.db import folders as store
from app.db.database import Database
from app.services import projects as project_service
from app.services.auth import CurrentSession

MAX_FOLDERS = 500
FolderRow = store.FolderRow


class FolderError(ValueError):
    """A change that would break the folder tree (shown to the person)."""


@dataclass(frozen=True, slots=True)
class Folders:
    folders: list[store.FolderRow]
    counts: dict[uuid.UUID, int]


def _clean(name: str) -> str:
    name = " ".join(name.split())
    if not 1 <= len(name) <= 100:
        raise FolderError("A folder name is 1 to 100 characters.")
    return name


async def list_folders(db: Database, session: CurrentSession) -> Folders:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        return Folders(
            await store.folders(conn, session.user.id), await store.counts(conn, session.user.id)
        )


async def _own(conn: AsyncConnection, folder_id: uuid.UUID) -> store.FolderRow:
    row = await store.folder(conn, folder_id)
    if row is None:
        raise authz.NotFoundError("Not found.")
    return row


def _tree_error(exc: IntegrityError) -> FolderError:
    text = str(exc.orig)
    if "inside itself" in text:
        return FolderError("A folder can't go inside itself or one of its own folders.")
    if "5 levels" in text:
        return FolderError("Folders go at most 5 levels deep.")
    return FolderError("That folder isn't there any more.")


async def create_folder(
    db: Database, session: CurrentSession, *, name: str, parent_id: uuid.UUID | None
) -> store.FolderRow:
    authz.require(session.principal, authz.Action.USE_APP)
    name = _clean(name)
    try:
        async with db.user_transaction(session.user.id) as conn:
            if len(await store.folders(conn, session.user.id)) >= MAX_FOLDERS:
                raise FolderError(f"You can have up to {MAX_FOLDERS} folders.")
            if parent_id is not None:
                await _own(conn, parent_id)
            folder_id = await store.create(conn, session.user.id, name, parent_id)
            return await _own(conn, folder_id)
    except IntegrityError as exc:
        raise _tree_error(exc) from None


UNCHANGED = object()


async def update_folder(
    db: Database,
    session: CurrentSession,
    folder_id: uuid.UUID,
    *,
    name: str | None = None,
    parent_id: uuid.UUID | object | None = UNCHANGED,
    position: float | None = None,
) -> store.FolderRow:
    """Rename a folder, move it into another folder (or to the top: parent_id None), or
    reorder it among its neighbours."""
    authz.require(session.principal, authz.Action.USE_APP)
    try:
        async with db.user_transaction(session.user.id) as conn:
            row = await _own(conn, folder_id)
            parent = row.parent_id if parent_id is UNCHANGED else parent_id
            if isinstance(parent, uuid.UUID):
                await _own(conn, parent)
            await store.update(
                conn,
                folder_id,
                name=_clean(name) if name is not None else row.name,
                parent_id=parent if isinstance(parent, uuid.UUID) else None,
                position=row.position if position is None else position,
            )
            return await _own(conn, folder_id)
    except IntegrityError as exc:
        raise _tree_error(exc) from None


async def delete_folder(db: Database, session: CurrentSession, folder_id: uuid.UUID) -> None:
    """Delete a folder. Its projects and folders move up a level; no project is deleted."""
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        await store.delete(conn, await _own(conn, folder_id))


async def file_project(
    db: Database, session: CurrentSession, project_id: uuid.UUID, folder_id: uuid.UUID | None
) -> None:
    """Put a project the person can see into one of their folders, or (None) take it out."""
    await project_service.get_project(db, session, project_id)  # authz + 404 if not visible
    async with db.user_transaction(session.user.id) as conn:
        if folder_id is not None:
            await _own(conn, folder_id)
        await store.place(conn, session.user.id, project_id, folder_id)
