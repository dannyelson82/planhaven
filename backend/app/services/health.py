"""Readiness (ARCHITECTURE.md §4.6): database reachable and migrated, and a worker alive."""

from datetime import timedelta

from app.db import health as db_health
from app.db import jobs as job_store
from app.db.database import Database
from app.db.migrations import head_revision

WORKER_STALE_AFTER = timedelta(seconds=60)


async def worker_alive(db: Database) -> bool:
    try:
        async with db.system_transaction() as conn:
            age = await job_store.newest_heartbeat_age(conn)
    except Exception:
        return False
    return age is not None and age <= WORKER_STALE_AFTER


async def is_ready(db: Database) -> bool:
    return await db_health.database_ready(db, head_revision()) and await worker_alive(db)
