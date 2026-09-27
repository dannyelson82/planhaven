"""Rate-limit bucket queries (system context)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def take(
    conn: AsyncConnection, key: str, *, capacity: float, per_second: float, cost: float = 1
) -> float:
    """Seconds to wait; 0 means allowed."""
    wait = await conn.scalar(
        text("SELECT app.rate_limit_take(:k, :c, :r, :n)"),
        {"k": key, "c": capacity, "r": per_second, "n": cost},
    )
    return float(wait or 0)


async def reset(conn: AsyncConnection, key: str) -> None:
    await conn.execute(text("DELETE FROM rate_limits WHERE bucket_key = :k"), {"k": key})


async def purge_idle(conn: AsyncConnection) -> int:
    """Drop buckets untouched for a day (they'd be full again anyway)."""
    result = await conn.execute(
        text("DELETE FROM rate_limits WHERE updated_at < now() - interval '1 day'")
    )
    return result.rowcount
