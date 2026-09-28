"""Contacts: contractors and suppliers, shared one by one like assets.

Sharing goes through app.services.sharing with kind="contact". A contact's page lists its
quotes on projects the viewer can see.
"""

import uuid
from typing import Any

from app import authz
from app.db import auth as audit
from app.db import contacts as store
from app.db import costs as cost_store
from app.db.database import Database
from app.services.auth import CurrentSession
from app.services.projects import ConflictError

ContactRow = store.ContactRow
QuoteRow = cost_store.QuoteRow


async def _access(conn: Any, contact_id: uuid.UUID) -> tuple[ContactRow, authz.ProjectAccess]:
    contact = await store.get_contact(conn, contact_id)
    if contact is None:
        raise authz.NotFoundError("Not found.")
    return contact, authz.ProjectAccess(contact.role)


async def list_contacts(db: Database, session: CurrentSession) -> list[ContactRow]:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        return [c for c in await store.list_contacts(conn) if c.role is not None]


async def get_contact(
    db: Database, session: CurrentSession, contact_id: uuid.UUID
) -> tuple[ContactRow, list[QuoteRow]]:
    async with db.user_transaction(session.user.id) as conn:
        contact, access = await _access(conn, contact_id)
        authz.require(session.principal, authz.Action.CONTACT_VIEW, access)
        return contact, await cost_store.quotes_for_contact(conn, contact_id)


async def create_contact(
    db: Database, session: CurrentSession, values: dict[str, str], ip: str | None
) -> ContactRow:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        contact_id = await store.create_contact(conn, user_id=session.user.id, values=values)
        await audit.record_audit(
            conn,
            action="contact.created",
            actor_user_id=session.user.id,
            ip=ip,
            resource_type="contact",
            resource_id=contact_id,
        )
        contact = await store.get_contact(conn, contact_id)
    if contact is None:
        raise RuntimeError("created contact not visible")
    return contact


async def update_contact(
    db: Database,
    session: CurrentSession,
    contact_id: uuid.UUID,
    expected_version: int,
    values: dict[str, str],
) -> ContactRow:
    async with db.user_transaction(session.user.id) as conn:
        _, access = await _access(conn, contact_id)
        authz.require(session.principal, authz.Action.CONTACT_EDIT, access)
        if await store.update_contact(conn, contact_id, expected_version, values) is None:
            raise ConflictError
        contact = await store.get_contact(conn, contact_id)
    if contact is None:
        raise authz.NotFoundError("Not found.")
    return contact


async def delete_contact(
    db: Database, session: CurrentSession, contact_id: uuid.UUID, ip: str | None
) -> None:
    async with db.user_transaction(session.user.id) as conn:
        _, access = await _access(conn, contact_id)
        authz.require(session.principal, authz.Action.CONTACT_VIEW, access)
        authz.require(session.principal, authz.Action.CONTACT_MANAGE, access)
        await store.delete_contact(conn, contact_id)
        await audit.record_audit(
            conn,
            action="contact.deleted",
            actor_user_id=session.user.id,
            ip=ip,
            resource_type="contact",
            resource_id=contact_id,
        )
