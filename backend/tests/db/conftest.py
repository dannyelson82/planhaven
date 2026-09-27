"""Database tests run against a real PostgreSQL (CI starts one). They're skipped when
PLANHAVEN_DB_HOST isn't set, e.g. on a laptop without PostgreSQL."""

import os
from collections.abc import AsyncIterator

import pytest
from alembic import command

from app.core.config import Settings
from app.db.database import OWNER_ROLE, Database
from app.db.migrations import alembic_config
from tests.conftest import make_settings

pytestmark = pytest.mark.db

if not os.environ.get("PLANHAVEN_DB_HOST"):
    pytest.skip("PLANHAVEN_DB_HOST not set; database tests skipped", allow_module_level=True)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
def migrated() -> None:
    command.upgrade(alembic_config(), "head")


def _settings() -> Settings:
    return make_settings(
        db_host=os.environ["PLANHAVEN_DB_HOST"],
        db_port=int(os.environ.get("PLANHAVEN_DB_PORT", "5432")),
    )


@pytest.fixture
async def db() -> AsyncIterator[Database]:
    database = Database(_settings())
    yield database
    await database.dispose()


@pytest.fixture
async def owner_db() -> AsyncIterator[Database]:
    database = Database(_settings(), role=OWNER_ROLE)
    yield database
    await database.dispose()


@pytest.fixture(autouse=True)
def fresh_rate_limits() -> None:
    """Tests share one client address; start each with empty rate-limit buckets. (Sync, with
    its own short-lived connection, so it also works for non-async tests.)"""
    import asyncio

    from sqlalchemy import text

    async def clear() -> None:
        database = Database(_settings())
        try:
            async with database.system_transaction() as conn:
                await conn.execute(text("DELETE FROM rate_limits"))
        finally:
            await database.dispose()

    asyncio.run(clear())
