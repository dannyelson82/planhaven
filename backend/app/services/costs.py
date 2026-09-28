"""Quotes and cost entries on a project: members read, editors write.

A quote may name a contact the editor can see and a document attached to the same project;
a cost entry may point at a quote of the same project. The database checks these links
again (migration 0016). Amounts are in cents (CAD by default).
"""

import uuid
from typing import Any

from app import authz
from app.db import auth as audit
from app.db import contacts as contact_store
from app.db import costs as store
from app.db import projects as project_store
from app.db.database import Database
from app.services import live
from app.services.auth import CurrentSession
from app.services.projects import ConflictError

QuoteRow = store.QuoteRow
CostRow = store.CostRow


class LinkError(Exception):
    """A link to something that isn't part of this project (message is safe to show)."""


async def _project_access(conn: Any, project_id: uuid.UUID) -> authz.ProjectAccess:
    access = authz.ProjectAccess(await project_store.role(conn, project_id))
    if access.role is not None and await project_store.get_project(conn, project_id) is None:
        return authz.ProjectAccess(None)
    return access


def _require(session: CurrentSession, access: authz.ProjectAccess, write: bool) -> None:
    authz.require(session.principal, authz.Action.PROJECT_VIEW, access)
    if write:
        authz.require(session.principal, authz.Action.PROJECT_EDIT, access)


async def _check_quote_links(
    conn: Any,
    project_id: uuid.UUID,
    values: dict[str, Any],
    previous: QuoteRow | None = None,
) -> None:
    contact_id = values.get("contact_id")
    if contact_id is not None and (previous is None or contact_id != previous.contact_id):
        contact = await contact_store.get_contact(conn, contact_id)
        if contact is None or contact.role is None:
            raise authz.NotFoundError("Not found.")
    attachment_id = values.get("attachment_id")
    if attachment_id is not None and not await store.attachment_in_project(
        conn, attachment_id, project_id
    ):
        raise LinkError("That document isn't attached to this project.")


async def quotes_for_project(
    db: Database, session: CurrentSession, project_id: uuid.UUID
) -> list[QuoteRow]:
    async with db.user_transaction(session.user.id) as conn:
        _require(session, await _project_access(conn, project_id), write=False)
        return await store.quotes_for_project(conn, project_id)


async def create_quote(
    db: Database,
    session: CurrentSession,
    project_id: uuid.UUID,
    values: dict[str, Any],
    ip: str | None,
) -> QuoteRow:
    async with db.user_transaction(session.user.id) as conn:
        _require(session, await _project_access(conn, project_id), write=True)
        await _check_quote_links(conn, project_id, values)
        quote_id = await store.create_quote(
            conn, project_id=project_id, user_id=session.user.id, values=values
        )
        await audit.record_audit(
            conn,
            action="quote.created",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=project_id,
            resource_type="quote",
            resource_id=quote_id,
        )
        quote = await store.get_quote(conn, quote_id)
    if quote is None:
        raise RuntimeError("created quote not visible")
    live.publish(project_id, "quotes")
    return quote


async def update_quote(
    db: Database,
    session: CurrentSession,
    quote_id: uuid.UUID,
    expected_version: int,
    changes: dict[str, Any],
) -> QuoteRow:
    """Change some fields of a quote; fields not given keep their value."""
    async with db.user_transaction(session.user.id) as conn:
        quote = await store.get_quote(conn, quote_id)
        if quote is None:
            raise authz.NotFoundError("Not found.")
        _require(session, await _project_access(conn, quote.project_id), write=True)
        values = {
            "contact_id": quote.contact_id,
            "title": quote.title,
            "amount_cents": quote.amount_cents,
            "status": quote.status,
            "attachment_id": quote.attachment_id,
            "notes": quote.notes,
            **changes,
        }
        await _check_quote_links(conn, quote.project_id, values, previous=quote)
        if await store.update_quote(conn, quote_id, expected_version, values) is None:
            raise ConflictError
        updated = await store.get_quote(conn, quote_id)
    if updated is None:
        raise authz.NotFoundError("Not found.")
    live.publish(updated.project_id, "quotes")
    return updated


async def delete_quote(
    db: Database, session: CurrentSession, quote_id: uuid.UUID, ip: str | None
) -> None:
    async with db.user_transaction(session.user.id) as conn:
        quote = await store.get_quote(conn, quote_id)
        if quote is None:
            raise authz.NotFoundError("Not found.")
        _require(session, await _project_access(conn, quote.project_id), write=True)
        await store.delete_quote(conn, quote_id)
        await audit.record_audit(
            conn,
            action="quote.deleted",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=quote.project_id,
            resource_type="quote",
            resource_id=quote_id,
        )
    live.publish(quote.project_id, "quotes")


async def costs_for_project(
    db: Database, session: CurrentSession, project_id: uuid.UUID
) -> list[CostRow]:
    async with db.user_transaction(session.user.id) as conn:
        _require(session, await _project_access(conn, project_id), write=False)
        return await store.costs_for_project(conn, project_id)


async def create_cost(
    db: Database,
    session: CurrentSession,
    project_id: uuid.UUID,
    values: dict[str, Any],
    ip: str | None,
) -> CostRow:
    async with db.user_transaction(session.user.id) as conn:
        _require(session, await _project_access(conn, project_id), write=True)
        if values.get("quote_id") is not None and not await store.quote_in_project(
            conn, values["quote_id"], project_id
        ):
            raise LinkError("That quote isn't part of this project.")
        cost_id = await store.create_cost(
            conn, project_id=project_id, user_id=session.user.id, values=values
        )
        await audit.record_audit(
            conn,
            action="cost.created",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=project_id,
            resource_type="cost",
            resource_id=cost_id,
        )
        cost = await store.get_cost(conn, cost_id)
    if cost is None:
        raise RuntimeError("created cost not visible")
    live.publish(project_id, "costs")
    return cost


async def delete_cost(
    db: Database, session: CurrentSession, cost_id: uuid.UUID, ip: str | None
) -> None:
    async with db.user_transaction(session.user.id) as conn:
        cost = await store.get_cost(conn, cost_id)
        if cost is None:
            raise authz.NotFoundError("Not found.")
        _require(session, await _project_access(conn, cost.project_id), write=True)
        await store.delete_cost(conn, cost_id)
        await audit.record_audit(
            conn,
            action="cost.deleted",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=cost.project_id,
            resource_type="cost",
            resource_id=cost_id,
        )
    live.publish(cost.project_id, "costs")
