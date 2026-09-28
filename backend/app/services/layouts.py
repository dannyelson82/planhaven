"""How a project page is arranged, per person (owner request, 2026-09-28).

The page is a grid of tiles: the groups (tasks, lists, notes, files, quotes and costs) and any
single note, list or file pulled out into its own tile, each narrow, wide or full width. Tasks
and quotes and costs always stay together, as do a list's items.

Someone who hasn't arranged a project's page sees the owner's arrangement (the person who
shared it), or the default; once they arrange it, they keep their own. Anyone who can see the
project can arrange their own view of it, viewers included. Tiles for things that were since
deleted, or that the person can't see, are simply not shown by the page.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from app import authz
from app.db import layouts as store
from app.db import projects as project_store
from app.db.database import Database
from app.services.auth import CurrentSession

GROUPS = ("tasks", "lists", "notes", "files", "money")
ITEMS = ("note", "list", "file")
WIDTHS = ("narrow", "wide", "full")

Source = Literal["mine", "owner", "default"]


@dataclass(frozen=True, slots=True)
class Layout:
    tiles: list[dict[str, Any]]
    source: Source


def complete(tiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Known tiles only, each once; every group present (missing ones at the end)."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for tile in tiles:
        kind, item, width = tile.get("kind"), tile.get("id"), tile.get("width", "full")
        if width not in WIDTHS:
            width = "full"
        if kind in GROUPS:
            key: tuple[str, str | None] = (kind, None)
            clean: dict[str, Any] = {"kind": kind, "width": width}
        elif kind in ITEMS and isinstance(item, str):
            try:
                key = (kind, str(uuid.UUID(item)))
            except ValueError:
                continue
            clean = {"kind": kind, "id": key[1], "width": width}
        else:
            continue
        if key not in seen:
            seen.add(key)
            out.append(clean)
    present = {t["kind"] for t in out}
    return out + [{"kind": g, "width": "full"} for g in GROUPS if g not in present]


DEFAULT: list[dict[str, Any]] = complete([])


async def _access(conn: Any, session: CurrentSession, project_id: uuid.UUID) -> None:
    access = authz.ProjectAccess(await project_store.role(conn, project_id))
    if access.role is not None and await project_store.get_project(conn, project_id) is None:
        access = authz.ProjectAccess(None)
    authz.require(session.principal, authz.Action.PROJECT_VIEW, access)


async def get_layout(db: Database, session: CurrentSession, project_id: uuid.UUID) -> Layout:
    async with db.user_transaction(session.user.id) as conn:
        await _access(conn, session, project_id)
        mine = await store.own(conn, project_id)
        if mine is not None:
            return Layout(complete(mine), "mine")
        shared = await store.owners(conn, project_id)
    if shared is not None:
        return Layout(complete(shared), "owner")
    return Layout(DEFAULT, "default")


async def save_layout(
    db: Database, session: CurrentSession, project_id: uuid.UUID, tiles: list[dict[str, Any]]
) -> Layout:
    arranged = complete(tiles)
    async with db.user_transaction(session.user.id) as conn:
        await _access(conn, session, project_id)
        await store.save(conn, project_id, arranged)
    return Layout(arranged, "mine")


async def reset_layout(db: Database, session: CurrentSession, project_id: uuid.UUID) -> Layout:
    async with db.user_transaction(session.user.id) as conn:
        await _access(conn, session, project_id)
        await store.reset(conn, project_id)
    return await get_layout(db, session, project_id)
