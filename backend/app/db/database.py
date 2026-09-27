"""Database access with Row-Level Security context (ARCHITECTURE.md §8.3, ADR 0004).

Every transaction declares who it acts for, before any query runs:

- `db.user_transaction(user_id)` sets `app.user_id`; RLS policies compare rows against it.
- `db.system_transaction()` sets `app.system` for narrowly scoped system jobs.
- A transaction that sets neither sees no user rows at all (policies fail closed).

Both settings are transaction-local (`set_config(..., true)`), so they can never leak to the
next request that reuses a pooled connection.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.core.config import Settings

APP_ROLE = "planhaven_app"
OWNER_ROLE = "planhaven_owner"


def database_url(settings: Settings, role: str) -> URL:
    # asyncpg treats a host starting with "/" as a Unix socket directory.
    return URL.create(
        "postgresql+asyncpg",
        username=role,
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
    )


class Database:
    def __init__(self, settings: Settings, role: str = APP_ROLE) -> None:
        self.engine: AsyncEngine = create_async_engine(
            database_url(settings, role),
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
            connect_args={"timeout": 5, "command_timeout": 30},
        )

    async def dispose(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def user_transaction(self, user_id: uuid.UUID) -> AsyncIterator[AsyncConnection]:
        """A transaction acting for `user_id`. Commits on success, rolls back on error."""
        if not isinstance(user_id, uuid.UUID):
            raise TypeError("user_id must be a UUID")
        async with self.engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)}
            )
            yield conn

    @asynccontextmanager
    async def system_transaction(self) -> AsyncIterator[AsyncConnection]:
        """A transaction for system jobs (recurrence, purges). Policies grant it only what
        they explicitly allow."""
        async with self.engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.system', 'true', true)"))
            yield conn

    @asynccontextmanager
    async def anonymous_transaction(self) -> AsyncIterator[AsyncConnection]:
        """A transaction with no identity: sees no user rows. For health checks and tests."""
        async with self.engine.begin() as conn:
            yield conn

    async def reachable(self) -> bool:
        try:
            async with self.anonymous_transaction() as conn:
                return bool((await conn.scalar(text("SELECT 1"))) == 1)
        except Exception:
            return False
