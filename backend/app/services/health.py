"""Readiness (ARCHITECTURE.md §4.6). Worker heartbeat is added with the worker."""

from app.db import health as db_health
from app.db.database import Database
from app.db.migrations import head_revision


async def is_ready(db: Database) -> bool:
    return await db_health.database_ready(db, head_revision())
