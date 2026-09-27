"""Database reachability check for /readyz."""

import asyncpg

# PostgreSQL listens only on a Unix socket inside the container (ARCHITECTURE.md §4.4).
SOCKET_DIR = "/run/postgresql"
DATABASE = "planhaven"
APP_ROLE = "planhaven_app"
TIMEOUT_SECONDS = 2.0


async def database_reachable() -> bool:
    try:
        conn = await asyncpg.connect(
            host=SOCKET_DIR, user=APP_ROLE, database=DATABASE, timeout=TIMEOUT_SECONDS
        )
    except OSError, TimeoutError, asyncpg.PostgresError:
        return False
    try:
        return bool(await conn.fetchval("SELECT 1", timeout=TIMEOUT_SECONDS) == 1)
    except OSError, TimeoutError, asyncpg.PostgresError:
        return False
    finally:
        await conn.close()
