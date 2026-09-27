"""Database checks for /readyz."""

from sqlalchemy import text

from app.db.database import Database


async def database_ready(db: Database, expected_revision: str | None) -> bool:
    """Reachable, and migrated to the revision this code expects."""
    try:
        async with db.anonymous_transaction() as conn:
            if (await conn.scalar(text("SELECT 1"))) != 1:
                return False
            if expected_revision is None:
                return True
            current = await conn.scalar(text("SELECT version_num FROM alembic_version"))
            return bool(current == expected_revision)
    except Exception:
        return False
