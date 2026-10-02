"""Queries for attachments (file metadata; the bytes are in the blob store)."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class AttachmentRow:
    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    kind: str
    content_type: str
    size: int
    blob_sha256: str
    thumb_sha256: str | None
    metadata_kept: bool
    created_by: uuid.UUID
    created_at: datetime
    list_item_id: uuid.UUID | None


async def attachments_for_project(
    conn: AsyncConnection, project_id: uuid.UUID
) -> list[AttachmentRow]:
    rows = await conn.execute(
        text("""
            SELECT id, project_id, filename, kind, content_type, size, blob_sha256,
                   thumb_sha256, metadata_kept, created_by, created_at, list_item_id
            FROM attachments WHERE project_id = :p AND deleted_at IS NULL
            ORDER BY created_at DESC LIMIT 500
        """),
        {"p": project_id},
    )
    return [AttachmentRow(**r._mapping) for r in rows]


async def get_attachment(conn: AsyncConnection, attachment_id: uuid.UUID) -> AttachmentRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, project_id, filename, kind, content_type, size, blob_sha256,
                       thumb_sha256, metadata_kept, created_by, created_at, list_item_id
                FROM attachments WHERE id = :id AND deleted_at IS NULL
            """),
            {"id": attachment_id},
        )
    ).first()
    return AttachmentRow(**row._mapping) if row else None


async def create_attachment(
    conn: AsyncConnection,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    filename: str,
    kind: str,
    content_type: str,
    size: int,
    blob_sha256: str,
    thumb_sha256: str | None,
    metadata_kept: bool,
    list_item_id: uuid.UUID | None = None,
) -> uuid.UUID:
    attachment_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO attachments (id, project_id, filename, kind, content_type, size,
                                     blob_sha256, thumb_sha256, metadata_kept, created_by,
                                     list_item_id)
            VALUES (:id, :p, :f, :k, :ct, :s, :b, :t, :m, :u, :item)
        """),
        {
            "id": attachment_id,
            "p": project_id,
            "f": filename,
            "k": kind,
            "ct": content_type,
            "s": size,
            "b": blob_sha256,
            "t": thumb_sha256,
            "m": metadata_kept,
            "u": user_id,
            "item": list_item_id,
        },
    )
    return attachment_id


async def item_in_project(conn: AsyncConnection, item_id: uuid.UUID, project_id: uuid.UUID) -> bool:
    found = await conn.scalar(
        text("SELECT 1 FROM list_items WHERE id = :i AND project_id = :p AND deleted_at IS NULL"),
        {"i": item_id, "p": project_id},
    )
    return found is not None


async def delete_attachment(conn: AsyncConnection, attachment_id: uuid.UUID) -> None:
    await conn.execute(
        text("UPDATE attachments SET deleted_at = now() WHERE id = :id AND deleted_at IS NULL"),
        {"id": attachment_id},
    )


async def referenced_blobs(conn: AsyncConnection) -> set[str]:
    """Every blob any attachment (including deleted ones in the trash), asset photo or contact
    photo uses. System context."""
    rows = await conn.execute(
        text("""
            SELECT blob_sha256 FROM attachments
            UNION SELECT thumb_sha256 FROM attachments WHERE thumb_sha256 IS NOT NULL
            UNION SELECT photo_sha256 FROM assets WHERE photo_sha256 IS NOT NULL
            UNION SELECT photo_thumb_sha256 FROM assets WHERE photo_thumb_sha256 IS NOT NULL
            UNION SELECT photo_sha256 FROM contacts WHERE photo_sha256 IS NOT NULL
            UNION SELECT photo_thumb_sha256 FROM contacts WHERE photo_thumb_sha256 IS NOT NULL
        """)
    )
    return {r[0] for r in rows}
