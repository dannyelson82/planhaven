"""Contacts: contractors and suppliers, shared one by one like assets.

Sharing goes through app.services.sharing with kind="contact". A contact's page lists its
quotes on projects the viewer can see.
"""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app import authz
from app.db import auth as audit
from app.db import contacts as store
from app.db import costs as cost_store
from app.db.database import Database
from app.services import attachments as attachment_service
from app.services import vcard
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


# ---------------------------------------------------------------- photo


async def set_photo(
    db: Database,
    blobs: attachment_service.BlobStore,
    session: CurrentSession,
    contact_id: uuid.UUID,
    *,
    chunks: AsyncIterator[bytes],
    max_bytes: int,
    ip: str | None,
) -> ContactRow:
    """Replace the contact's photo (editors). Cleaned like any photo: no location."""
    async with db.user_transaction(session.user.id) as conn:
        _, access = await _access(conn, contact_id)
        authz.require(session.principal, authz.Action.CONTACT_EDIT, access)
    photo, thumb, content_type = await attachment_service.receive_photo(
        db, blobs, session, chunks=chunks, max_bytes=max_bytes, ip=ip
    )
    async with db.user_transaction(session.user.id) as conn:
        _, access = await _access(conn, contact_id)
        authz.require(session.principal, authz.Action.CONTACT_EDIT, access)
        await store.set_photo(conn, contact_id, photo, thumb, content_type)
        contact = await store.get_contact(conn, contact_id)
    if contact is None:
        raise authz.NotFoundError("Not found.")
    return contact


async def remove_photo(db: Database, session: CurrentSession, contact_id: uuid.UUID) -> None:
    async with db.user_transaction(session.user.id) as conn:
        _, access = await _access(conn, contact_id)
        authz.require(session.principal, authz.Action.CONTACT_EDIT, access)
        await store.set_photo(conn, contact_id, None, None, None)


async def photo(
    db: Database, session: CurrentSession, contact_id: uuid.UUID, *, thumbnail: bool
) -> tuple[str, str]:
    """(blob, content type) of the contact's photo or thumbnail, for people who can see it."""
    async with db.user_transaction(session.user.id) as conn:
        contact, access = await _access(conn, contact_id)
        authz.require(session.principal, authz.Action.CONTACT_VIEW, access)
    if contact.photo_sha256 is None or contact.photo_thumb_sha256 is None:
        raise authz.NotFoundError("No photo.")
    if thumbnail:
        return contact.photo_thumb_sha256, "image/webp"
    return contact.photo_sha256, contact.photo_type or "image/jpeg"


# ---------------------------------------------------------------- contact cards (.vcf)


async def _one_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


async def import_card(
    db: Database,
    blobs: attachment_service.BlobStore,
    session: CurrentSession,
    data: bytes,
    *,
    kind: str,
    max_photo_bytes: int,
    ip: str | None,
) -> ContactRow:
    """A new contact from a contact card shared from a phone (vcard.VCardError if it isn't
    one). Its photo, if any, is cleaned like any upload; a photo that can't be used is left
    out rather than failing the import."""
    card = vcard.parse(data)
    contact = await create_contact(
        db,
        session,
        {
            "name": card.name,
            "company": card.company,
            "kind": kind,
            "phone": card.phone,
            "email": card.email,
            "website": card.website,
            "notes": card.notes,
        },
        ip,
    )
    if card.photo:
        with contextlib.suppress(
            attachment_service.UploadTooLargeError, attachment_service.UnsupportedFileError
        ):
            contact = await set_photo(
                db,
                blobs,
                session,
                contact.id,
                chunks=_one_chunk(card.photo),
                max_bytes=max_photo_bytes,
                ip=ip,
            )
    return contact


async def export_card(
    db: Database,
    blobs: attachment_service.BlobStore,
    session: CurrentSession,
    contact_id: uuid.UUID,
) -> tuple[str, str]:
    """(file name, vCard text) for saving the contact to a phone, with its (cleaned) photo."""
    contact, _ = await get_contact(db, session, contact_id)
    photo = None
    if contact.photo_sha256:
        path = blobs.path(contact.photo_sha256)
        size = await asyncio.to_thread(lambda: path.stat().st_size)
        if size <= vcard.MAX_PHOTO_BYTES:
            photo = await asyncio.to_thread(path.read_bytes)
    card = vcard.Card(
        name=contact.name,
        company=contact.company,
        phone=contact.phone,
        email=contact.email,
        website=contact.website,
        notes=contact.notes,
        photo=photo,
    )
    return f"{contact.name}.vcf", vcard.build(card, contact.photo_type)
