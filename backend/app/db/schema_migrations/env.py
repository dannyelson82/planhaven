"""Alembic environment. Migrations run as the table-owner role, never as the app role
(ARCHITECTURE.md §8.3)."""

import asyncio
import os

from alembic import context
from sqlalchemy.engine import URL, Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.database import OWNER_ROLE


def owner_url() -> URL:
    return URL.create(
        "postgresql+asyncpg",
        username=OWNER_ROLE,
        host=os.environ.get("PLANHAVEN_DB_HOST", "/run/postgresql"),
        port=int(os.environ.get("PLANHAVEN_DB_PORT", "5432")),
        database="planhaven",
    )


def run_sync(connection: Connection) -> None:
    context.configure(connection=connection, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async() -> None:
    engine = create_async_engine(owner_url())
    async with engine.connect() as connection:
        await connection.run_sync(run_sync)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported.")
asyncio.run(run_async())
