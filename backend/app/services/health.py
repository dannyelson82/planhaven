"""Readiness (ARCHITECTURE.md §4.6). Migrations and worker heartbeat are added with those
components."""

from app.db import health as db_health


async def is_ready() -> bool:
    return await db_health.database_reachable()
