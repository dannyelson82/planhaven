"""Attachments: upload, list, download and delete files on a project (ARCHITECTURE.md §10).

Upload pipeline: permission and rate-limit checks → streamed to a temporary file with a hard
size limit → type detected from the bytes → allowlist → images cleaned (location removed)
and thumbnailed in a separate limited process → stored by hash → row created (RLS).
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app import authz
from app.db import attachments as store
from app.db import auth as audit
from app.db import projects as project_store
from app.db.database import Database
from app.files import images, sniff
from app.files.blobs import BlobStore, TooLargeError

__all__ = ["BlobStore"]
from app.services import limits, live
from app.services.auth import CurrentSession

AttachmentRow = store.AttachmentRow

UPLOAD_USER = limits.Limit("upload-user", capacity=60, per_second=1 / 10)


class UploadTooLargeError(Exception):
    pass


class UnsupportedFileError(Exception):
    pass


async def _access(conn: Any, project_id: uuid.UUID) -> authz.ProjectAccess:
    access = authz.ProjectAccess(await project_store.role(conn, project_id))
    if access.role is not None and await project_store.get_project(conn, project_id) is None:
        return authz.ProjectAccess(None)
    return access


def _require(session: CurrentSession, access: authz.ProjectAccess, write: bool) -> None:
    authz.require(session.principal, authz.Action.PROJECT_VIEW, access)
    if write:
        authz.require(session.principal, authz.Action.PROJECT_EDIT, access)


async def attachments_for_project(
    db: Database, session: CurrentSession, project_id: uuid.UUID
) -> list[AttachmentRow]:
    async with db.user_transaction(session.user.id) as conn:
        _require(session, await _access(conn, project_id), write=False)
        return await store.attachments_for_project(conn, project_id)


async def get_attachment(
    db: Database, session: CurrentSession, attachment_id: uuid.UUID
) -> tuple[AttachmentRow, bool]:
    """The attachment and whether this user may delete it."""
    async with db.user_transaction(session.user.id) as conn:
        row = await store.get_attachment(conn, attachment_id)
        if row is None:
            raise authz.NotFoundError("Not found.")
        access = await _access(conn, row.project_id)
        _require(session, access, write=False)
        return row, access.role in ("owner", "editor")


async def upload(
    db: Database,
    blobs: BlobStore,
    session: CurrentSession,
    project_id: uuid.UUID,
    *,
    filename: str,
    keep_metadata: bool,
    chunks: AsyncIterator[bytes],
    max_bytes: int,
    ip: str | None,
) -> AttachmentRow:
    # Refuse early, before reading a byte of the body.
    async with db.user_transaction(session.user.id) as conn:
        _require(session, await _access(conn, project_id), write=True)
    await limits.check(
        db,
        [(UPLOAD_USER, limits.key(UPLOAD_USER, session.user.id))],
        ip=ip,
        user_id=session.user.id,
    )

    with blobs.temp_file() as tmp:
        try:
            received = await blobs.receive(chunks, tmp, max_bytes)
        except TooLargeError:
            raise UploadTooLargeError from None
        file_type = sniff.detect(received.head, filename, received.size)
        if file_type is None or received.size == 0:
            raise UnsupportedFileError("This type of file isn't supported.")
        thumb_sha: str | None = None
        size = received.size
        if file_type.kind == "image":
            data = await asyncio.to_thread(Path(tmp).read_bytes)
            try:
                if file_type is sniff.HEIC:
                    # iPhone photo: decoded to JPEG first (images.heic_to_jpeg).
                    jpeg = await images.heic_to_jpeg(data, blobs.incoming)
                    if keep_metadata:
                        # Keep the original file as it is; the thumbnail comes from the JPEG.
                        _, thumbnail = await images.clean(jpeg, keep_metadata=False)
                        cleaned = data
                    else:
                        cleaned, thumbnail = await images.clean(jpeg, keep_metadata=False)
                        file_type = sniff.JPEG
                else:
                    cleaned, thumbnail = await images.clean(data, keep_metadata=keep_metadata)
            except images.ImageError:
                raise UnsupportedFileError("This image couldn't be read.") from None
            blob_sha = await asyncio.to_thread(blobs.put, cleaned)
            thumb_sha = await asyncio.to_thread(blobs.put, thumbnail)
            size = len(cleaned)
        else:
            blob_sha = received.sha256
            await asyncio.to_thread(blobs.adopt, tmp, blob_sha)

    async with db.user_transaction(session.user.id) as conn:
        _require(session, await _access(conn, project_id), write=True)
        attachment_id = await store.create_attachment(
            conn,
            project_id=project_id,
            user_id=session.user.id,
            filename=sniff.safe_filename(filename, file_type),
            kind=file_type.kind,
            content_type=file_type.mime,
            size=size,
            blob_sha256=blob_sha,
            thumb_sha256=thumb_sha,
            metadata_kept=keep_metadata and file_type.kind == "image",
        )
        await audit.record_audit(
            conn,
            action="attachment.created",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=project_id,
            resource_type="attachment",
            resource_id=attachment_id,
        )
        row = await store.get_attachment(conn, attachment_id)
    if row is None:
        raise RuntimeError("created attachment not visible")
    live.publish(project_id, "attachments")
    return row


async def delete_attachment(
    db: Database, session: CurrentSession, attachment_id: uuid.UUID, ip: str | None
) -> None:
    async with db.user_transaction(session.user.id) as conn:
        row = await store.get_attachment(conn, attachment_id)
        if row is None:
            raise authz.NotFoundError("Not found.")
        _require(session, await _access(conn, row.project_id), write=True)
        await store.delete_attachment(conn, attachment_id)
        await audit.record_audit(
            conn,
            action="attachment.deleted",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=row.project_id,
            resource_type="attachment",
            resource_id=attachment_id,
        )
    live.publish(row.project_id, "attachments")


async def purge_blobs(db: Database, blobs: BlobStore) -> int:
    """Delete stored files no attachment refers to any more (maintenance job)."""
    async with db.system_transaction() as conn:
        referenced = await store.referenced_blobs(conn)
    return await asyncio.to_thread(blobs.purge, referenced)
