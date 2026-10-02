"""Lists and list items (shopping, parts, checklists). Same rules as tasks: members read,
owners and editors write (authz + RLS). Creating items accepts an idempotency key so offline
clients can safely replay (A§13.4); checking items off is a plain state change and doesn't
need the item's version, so it never conflicts."""

import json
import uuid
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from app import authz
from app.db import auth as audit
from app.db import lists as store
from app.db import projects as project_store
from app.db.database import Database
from app.services import live, merge
from app.services.auth import CurrentSession
from app.services.projects import ConflictError

ListRow = store.ListRow
ItemRow = store.ItemRow
KINDS = ("shopping", "parts", "checklist")


async def _access(conn: Any, project_id: uuid.UUID) -> authz.ProjectAccess:
    access = authz.ProjectAccess(await project_store.role(conn, project_id))
    if access.role is not None and await project_store.get_project(conn, project_id) is None:
        return authz.ProjectAccess(None)
    return access


async def _list_access(conn: Any, list_id: uuid.UUID) -> tuple[ListRow, authz.ProjectAccess]:
    row = await store.get_list(conn, list_id)
    if row is None:
        raise authz.NotFoundError("Not found.")
    return row, await _access(conn, row.project_id)


async def _item_access(conn: Any, item_id: uuid.UUID) -> tuple[ItemRow, authz.ProjectAccess]:
    row = await store.get_item(conn, item_id)
    if row is None:
        raise authz.NotFoundError("Not found.")
    return row, await _access(conn, row.project_id)


def _can(session: CurrentSession, access: authz.ProjectAccess, write: bool) -> None:
    authz.require(session.principal, authz.Action.PROJECT_VIEW, access)
    if write:
        authz.require(session.principal, authz.Action.PROJECT_EDIT, access)


async def lists_for_project(
    db: Database, session: CurrentSession, project_id: uuid.UUID
) -> list[ListRow]:
    async with db.user_transaction(session.user.id) as conn:
        _can(session, await _access(conn, project_id), write=False)
        return await store.lists_for_project(conn, project_id)


async def create_list(
    db: Database,
    session: CurrentSession,
    project_id: uuid.UUID,
    *,
    title: str,
    kind: str,
    ip: str | None,
) -> ListRow:
    async with db.user_transaction(session.user.id) as conn:
        _can(session, await _access(conn, project_id), write=True)
        list_id = await store.create_list(
            conn, project_id=project_id, user_id=session.user.id, title=title, kind=kind
        )
        await audit.record_audit(
            conn,
            action="list.created",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=project_id,
            resource_type="list",
            resource_id=list_id,
        )
        row = await store.get_list(conn, list_id)
    if row is None:
        raise RuntimeError("created list not visible")
    live.publish(project_id, "lists")
    return row


async def get_list(
    db: Database, session: CurrentSession, list_id: uuid.UUID
) -> tuple[ListRow, list[ItemRow]]:
    async with db.user_transaction(session.user.id) as conn:
        row, access = await _list_access(conn, list_id)
        _can(session, access, write=False)
        return row, await store.items(conn, list_id)


async def update_list(
    db: Database,
    session: CurrentSession,
    list_id: uuid.UUID,
    *,
    expected_version: int,
    title: str | None,
    kind: str | None,
    ip: str | None,
) -> ListRow:
    async with db.user_transaction(session.user.id) as conn:
        row, access = await _list_access(conn, list_id)
        _can(session, access, write=True)
        if (
            await store.update_list(
                conn, list_id, expected_version=expected_version, title=title, kind=kind
            )
            is None
        ):
            raise ConflictError("This list was changed elsewhere. Reload and try again.")
        await audit.record_audit(
            conn,
            action="list.updated",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=row.project_id,
            resource_type="list",
            resource_id=list_id,
        )
        after = await store.get_list(conn, list_id)
    if after is None:
        raise authz.NotFoundError("Not found.")
    live.publish(row.project_id, "lists")
    return after


async def delete_list(
    db: Database, session: CurrentSession, list_id: uuid.UUID, ip: str | None
) -> None:
    async with db.user_transaction(session.user.id) as conn:
        row, access = await _list_access(conn, list_id)
        _can(session, access, write=True)
        await store.delete_list(conn, list_id)
        await audit.record_audit(
            conn,
            action="list.deleted",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=row.project_id,
            resource_type="list",
            resource_id=list_id,
        )
    live.publish(row.project_id, "lists")


async def add_item(
    db: Database,
    session: CurrentSession,
    list_id: uuid.UUID,
    *,
    text: str,
    quantity: Decimal | None,
    unit: str | None,
    price_cents: int | None,
    idempotency_key: str | None,
    ip: str | None,
) -> ItemRow:
    async with db.user_transaction(session.user.id) as conn:
        row, access = await _list_access(conn, list_id)
        _can(session, access, write=True)
        scope = f"list-item:{list_id}"
        existing = (
            await store.remembered(conn, session.user.id, idempotency_key, scope)
            if idempotency_key
            else None
        )
        item_id = existing or uuid.uuid7()
        if existing is None:
            await store.create_item(
                conn,
                item_id=item_id,
                list_id=list_id,
                project_id=row.project_id,
                user_id=session.user.id,
                text_=text,
                quantity=quantity,
                unit=unit,
                price_cents=price_cents,
            )
            if idempotency_key:
                await store.remember(conn, session.user.id, idempotency_key, scope, item_id)
            await audit.record_audit(
                conn,
                action="list_item.created",
                actor_user_id=session.user.id,
                ip=ip,
                project_id=row.project_id,
                resource_type="list_item",
                resource_id=item_id,
            )
        item = await store.get_item(conn, item_id)
    if item is None:
        raise authz.NotFoundError("Not found.")
    live.publish(row.project_id, "lists")
    return item


MAX_BULK_ITEMS = 200


async def add_items(
    db: Database,
    session: CurrentSession,
    list_id: uuid.UUID,
    texts: list[str],
    *,
    idempotency_key: str | None,
    ip: str | None,
) -> int:
    """Adds many items at once (a pasted list, one item per line). Returns how many."""
    if not texts or len(texts) > MAX_BULK_ITEMS:
        raise ValueError("1 to 200 items")
    async with db.user_transaction(session.user.id) as conn:
        row, access = await _list_access(conn, list_id)
        _can(session, access, write=True)
        scope = f"list-items:{list_id}"
        if idempotency_key and await store.remembered(
            conn, session.user.id, idempotency_key, scope
        ):
            return len(texts)  # already added (an offline replay)
        first = uuid.uuid7()
        for i, text in enumerate(texts):
            await store.create_item(
                conn,
                item_id=first if i == 0 else uuid.uuid7(),
                list_id=list_id,
                project_id=row.project_id,
                user_id=session.user.id,
                text_=text,
                quantity=None,
                unit=None,
                price_cents=None,
            )
        if idempotency_key:
            await store.remember(conn, session.user.id, idempotency_key, scope, first)
        await audit.record_audit(
            conn,
            action="list_item.created",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=row.project_id,
            resource_type="list",
            resource_id=list_id,
            details=json.dumps({"count": len(texts)}),
        )
    live.publish(row.project_id, "lists")
    return len(texts)


async def move_items(
    db: Database,
    session: CurrentSession,
    list_id: uuid.UUID,
    item_ids: list[uuid.UUID],
    *,
    to_list_id: uuid.UUID,
    ip: str | None,
) -> int:
    """Moves items to another list of the same project ("sort a big list later")."""
    async with db.user_transaction(session.user.id) as conn:
        source, access = await _list_access(conn, list_id)
        _can(session, access, write=True)
        target, _ = await _list_access(conn, to_list_id)
        if target.project_id != source.project_id:
            raise authz.NotFoundError("Not found.")  # only within a project
        if to_list_id == list_id:
            return 0
        moved = await store.move_items(conn, item_ids, from_list=list_id, to_list=to_list_id)
        await audit.record_audit(
            conn,
            action="list_item.moved",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=source.project_id,
            resource_type="list",
            resource_id=to_list_id,
            details=json.dumps({"count": moved, "from": str(list_id)}),
        )
    live.publish(source.project_id, "lists")
    return moved


async def update_item(
    db: Database,
    session: CurrentSession,
    item_id: uuid.UUID,
    *,
    expected_version: int | None,
    fields: dict[str, Any],
    ip: str | None,
    base: dict[str, Any] | None = None,
) -> ItemRow:
    """`fields` holds only what the client sent. Only a pure check-off may omit the version.
    `base`: the values the changed fields had when the client started (merge.unchanged_since)."""
    only_check = set(fields) <= {"checked"}
    if expected_version is None and not only_check:
        raise ValueError("version required")
    async with db.user_transaction(session.user.id) as conn:
        before, access = await _item_access(conn, item_id)
        _can(session, access, write=True)
        expected = None if only_check else expected_version
        if (
            expected is not None
            and expected != before.version
            and merge.unchanged_since(asdict(before), fields, base, ignore={"checked"})
        ):
            expected = before.version  # only other fields changed meanwhile: keep both
        version = await store.update_item(
            conn,
            item_id,
            user_id=session.user.id,
            expected_version=expected,
            text_=fields.get("text"),
            quantity=fields.get("quantity"),
            set_quantity="quantity" in fields,
            unit=fields.get("unit"),
            set_unit="unit" in fields,
            price_cents=fields.get("price_cents"),
            set_price="price_cents" in fields,
            notes=fields.get("notes"),
            website=fields.get("website"),
            checked=fields.get("checked"),
        )
        if version is None:
            raise ConflictError("This item was changed elsewhere. Reload and try again.")
        if fields.get("checked") is True and before.checked_at is None:
            await project_store.emit(
                conn,
                "list_item.checked",
                user_id=session.user.id,
                project_id=before.project_id,
                payload={"item_id": str(item_id)},
            )
        await audit.record_audit(
            conn,
            action="list_item.updated",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=before.project_id,
            resource_type="list_item",
            resource_id=item_id,
        )
        item = await store.get_item(conn, item_id)
    if item is None:
        raise authz.NotFoundError("Not found.")
    live.publish(before.project_id, "lists")
    return item


async def delete_item(
    db: Database, session: CurrentSession, item_id: uuid.UUID, ip: str | None
) -> None:
    async with db.user_transaction(session.user.id) as conn:
        before, access = await _item_access(conn, item_id)
        _can(session, access, write=True)
        await store.delete_item(conn, item_id)
        await audit.record_audit(
            conn,
            action="list_item.deleted",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=before.project_id,
            resource_type="list_item",
            resource_id=item_id,
        )
    live.publish(before.project_id, "lists")


Suggestion = store.Suggestion
MAX_SUGGESTIONS = 8


async def suggestions(db: Database, session: CurrentSession, query: str) -> list[Suggestion]:
    """Items this person added before, on any list they can see, for the words typed so far."""
    authz.require(session.principal, authz.Action.USE_APP)
    query = " ".join(query.split())
    if not query:
        return []
    async with db.user_transaction(session.user.id) as conn:
        return await store.suggestions(conn, query, MAX_SUGGESTIONS)
