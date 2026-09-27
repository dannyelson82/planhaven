"""Queries for plugin state (system context) and plugin data (user context, RLS)."""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def enabled_ids(conn: AsyncConnection) -> set[str]:
    rows = await conn.execute(text("SELECT plugin_id FROM plugin_states WHERE enabled"))
    return set(rows.scalars())


async def set_enabled(
    conn: AsyncConnection, plugin_id: str, enabled: bool, user_id: uuid.UUID
) -> None:
    await conn.execute(
        text("""
            INSERT INTO plugin_states (plugin_id, enabled, changed_by) VALUES (:p, :e, :u)
            ON CONFLICT (plugin_id) DO UPDATE
                SET enabled = :e, changed_by = :u, changed_at = now()
        """),
        {"p": plugin_id, "e": enabled, "u": user_id},
    )


async def get_data(
    conn: AsyncConnection, plugin_id: str, scope: str, scope_id: uuid.UUID, key: str
) -> Any | None:
    value = await conn.scalar(
        text(
            "SELECT value FROM plugin_data WHERE plugin_id = :p AND scope = :s "
            "AND scope_id = :sid AND key = :k"
        ),
        {"p": plugin_id, "s": scope, "sid": scope_id, "k": key},
    )
    return value


async def put_data(
    conn: AsyncConnection,
    plugin_id: str,
    scope: str,
    scope_id: uuid.UUID,
    key: str,
    value: Any,
    user_id: uuid.UUID,
) -> None:
    await conn.execute(
        text("""
            INSERT INTO plugin_data (plugin_id, scope, scope_id, key, value, updated_by)
            VALUES (:p, :s, :sid, :k, CAST(:v AS jsonb), :u)
            ON CONFLICT (plugin_id, scope, scope_id, key) DO UPDATE
                SET value = CAST(:v AS jsonb), updated_by = :u, updated_at = now(),
                    version = plugin_data.version + 1
        """),
        {
            "p": plugin_id,
            "s": scope,
            "sid": scope_id,
            "k": key,
            "v": json.dumps(value),
            "u": user_id,
        },
    )
