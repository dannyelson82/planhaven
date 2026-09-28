"""Queries for contacts (contractors, suppliers) and their members."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

FIELDS = ("name", "company", "kind", "phone", "email", "website", "notes")


@dataclass(frozen=True, slots=True)
class ContactRow:
    id: uuid.UUID
    name: str
    company: str
    kind: str
    phone: str
    email: str
    website: str
    notes: str
    role: str | None
    updated_at: datetime
    version: int
    photo_sha256: str | None = None
    photo_thumb_sha256: str | None = None
    photo_type: str | None = None


async def role(conn: AsyncConnection, contact_id: uuid.UUID) -> str | None:
    value = await conn.scalar(text("SELECT app.contact_role(:c)"), {"c": contact_id})
    return str(value) if value is not None else None


async def list_contacts(conn: AsyncConnection) -> list[ContactRow]:
    rows = await conn.execute(
        text("""
            SELECT id, name, company, kind, phone, email, website, notes,
                   app.contact_role(id) AS role, updated_at, version,
                   photo_sha256, photo_thumb_sha256, photo_type
            FROM contacts WHERE deleted_at IS NULL ORDER BY name LIMIT 1000
        """)
    )
    return [ContactRow(**r._mapping) for r in rows]


async def get_contact(conn: AsyncConnection, contact_id: uuid.UUID) -> ContactRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, name, company, kind, phone, email, website, notes,
                       app.contact_role(id) AS role, updated_at, version,
                   photo_sha256, photo_thumb_sha256, photo_type
                FROM contacts WHERE id = :id AND deleted_at IS NULL
            """),
            {"id": contact_id},
        )
    ).first()
    return ContactRow(**row._mapping) if row else None


async def create_contact(
    conn: AsyncConnection, *, user_id: uuid.UUID, values: dict[str, str]
) -> uuid.UUID:
    contact_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO contacts (id, name, company, kind, phone, email, website, notes,
                                  created_by)
            VALUES (:id, :name, :company, :kind, :phone, :email, :website, :notes, :u)
        """),
        {"id": contact_id, "u": user_id, **{f: values[f] for f in FIELDS}},
    )
    await conn.execute(
        text("INSERT INTO contact_members (contact_id, user_id, role) VALUES (:c, :u, 'owner')"),
        {"c": contact_id, "u": user_id},
    )
    return contact_id


async def update_contact(
    conn: AsyncConnection, contact_id: uuid.UUID, expected_version: int, values: dict[str, str]
) -> int | None:
    v = await conn.scalar(
        text("""
            UPDATE contacts SET name = :name, company = :company, kind = :kind, phone = :phone,
                                email = :email, website = :website, notes = :notes,
                                updated_at = now(), version = version + 1
            WHERE id = :id AND version = :v AND deleted_at IS NULL RETURNING version
        """),
        {"id": contact_id, "v": expected_version, **{f: values[f] for f in FIELDS}},
    )
    return int(v) if v is not None else None


async def delete_contact(conn: AsyncConnection, contact_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "UPDATE contacts SET deleted_at = now(), updated_at = now(), version = version + 1 "
            "WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": contact_id},
    )


async def set_photo(
    conn: AsyncConnection,
    contact_id: uuid.UUID,
    photo: str | None,
    thumb: str | None,
    content_type: str | None,
) -> bool:
    result = await conn.execute(
        text("""
            UPDATE contacts SET photo_sha256 = :p, photo_thumb_sha256 = :t, photo_type = :ct,
                                updated_at = now(), version = version + 1
            WHERE id = :id AND deleted_at IS NULL
        """),
        {"id": contact_id, "p": photo, "t": thumb, "ct": content_type},
    )
    return result.rowcount == 1
