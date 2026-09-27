"""Job queue behaviour and isolation (ADR 0003, ADR 0004)."""

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import jobs as job_store
from app.db.database import Database
from app.services import health as health_service
from app.workers import runner
from app.workers.registry import JobContext, registered
from app.workers.runner import Worker, backoff

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def _status(db: Database, job_id: uuid.UUID) -> dict[str, Any]:
    async with db.system_transaction() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status, attempts, last_error, run_after > now() AS delayed "
                    "FROM jobs WHERE id = :id"
                ),
                {"id": job_id},
            )
        ).one()
    return dict(row._mapping)


async def _drain(db: Database) -> None:
    """Park every due job from earlier tests so each test sees only its own."""
    async with db.system_transaction() as conn:
        await conn.execute(
            text("UPDATE jobs SET status = 'dead' WHERE status IN ('queued', 'running')")
        )


async def test_job_runs_as_the_user_who_enqueued_it(db: Database) -> None:
    await _drain(db)
    user = uuid.uuid7()
    seen: dict[str, Any] = {}

    async def handler(ctx: JobContext, payload: dict[str, Any]) -> None:
        async with ctx.transaction() as conn:
            seen["identity"] = await conn.scalar(text("SELECT app.current_user_id()"))
            seen["system"] = await conn.scalar(text("SELECT app.is_system()"))
        seen["payload"] = payload

    async with db.user_transaction(user) as conn:
        job_id = await job_store.enqueue(conn, "test.identity", {"n": 1}, user_id=user)

    async with registered("test.identity", handler):
        assert await Worker(db, "test").run_once() is True

    assert seen == {"identity": user, "system": False, "payload": {"n": 1}}
    assert (await _status(db, job_id))["status"] == "done"


async def test_users_cannot_read_or_forge_jobs(db: Database) -> None:
    user = uuid.uuid7()
    async with db.user_transaction(user) as conn:
        await job_store.enqueue(conn, "test.x", user_id=user)
        assert await conn.scalar(text("SELECT count(*) FROM jobs")) == 0

    with pytest.raises(DBAPIError, match="row-level security"):
        async with db.user_transaction(user) as conn:
            await job_store.enqueue(conn, "test.x", user_id=uuid.uuid7())

    with pytest.raises(DBAPIError, match="row-level security"):
        async with db.user_transaction(user) as conn:
            await conn.execute(
                text("INSERT INTO jobs (kind, user_id, status) VALUES ('x', :u, 'done')"),
                {"u": user},
            )


async def test_failures_retry_with_backoff_then_die(db: Database) -> None:
    await _drain(db)
    calls = 0

    async def failing(ctx: JobContext, payload: dict[str, Any]) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("contains user data: secret")

    async with db.system_transaction() as conn:
        job_id = await job_store.enqueue(conn, "test.fail", user_id=None, max_attempts=2)

    async with registered("test.fail", failing):
        worker = Worker(db, "test")
        assert await worker.run_once() is True
        state = await _status(db, job_id)
        assert state == {
            "status": "queued",
            "attempts": 1,
            "last_error": "RuntimeError",
            "delayed": True,
        }
        assert await worker.run_once() is False  # not due yet

        async with db.system_transaction() as conn:
            await conn.execute(
                text("UPDATE jobs SET run_after = now() WHERE id = :id"), {"id": job_id}
            )
        assert await worker.run_once() is True

    state = await _status(db, job_id)
    assert state["status"] == "dead"
    assert state["attempts"] == 2
    assert calls == 2


async def test_unknown_kind_goes_straight_to_dead(db: Database) -> None:
    await _drain(db)
    async with db.system_transaction() as conn:
        job_id = await job_store.enqueue(conn, "test.no-such-kind", user_id=None)

    assert await Worker(db, "test").run_once() is True
    state = await _status(db, job_id)
    assert (state["status"], state["last_error"]) == ("dead", "LookupError")


async def test_expired_lease_is_reclaimed(db: Database) -> None:
    await _drain(db)
    async with db.system_transaction() as conn:
        job_id = await job_store.enqueue(conn, "test.reclaim", user_id=None)
        await conn.execute(
            text(
                "UPDATE jobs SET status = 'running', attempts = 1, "
                "locked_until = now() - interval '1 second' WHERE id = :id"
            ),
            {"id": job_id},
        )

    async def ok(ctx: JobContext, payload: dict[str, Any]) -> None:
        pass

    async with registered("test.reclaim", ok):
        assert await Worker(db, "test").run_once() is True
    state = await _status(db, job_id)
    assert (state["status"], state["attempts"]) == ("done", 2)


async def test_concurrent_workers_never_claim_the_same_job(db: Database) -> None:
    await _drain(db)
    async with db.system_transaction() as conn:
        ids = {await job_store.enqueue(conn, "test.parallel", user_id=None) for _ in range(6)}

    claimed: list[uuid.UUID] = []

    async def record(ctx: JobContext, payload: dict[str, Any]) -> None:
        claimed.append(ctx.job_id)
        await asyncio.sleep(0.05)

    async with registered("test.parallel", record):
        workers = [Worker(db, f"w{i}") for i in range(3)]
        for _ in range(2):
            await asyncio.gather(*(w.run_once() for w in workers))

    assert sorted(claimed) == sorted(ids)


async def test_payload_size_is_limited(db: Database) -> None:
    with pytest.raises(ValueError, match="too large"):
        async with db.system_transaction() as conn:
            await job_store.enqueue(conn, "test.big", {"x": "a" * 70_000}, user_id=None)


async def test_readiness_needs_a_fresh_worker_heartbeat(db: Database) -> None:
    async with db.system_transaction() as conn:
        await conn.execute(text("DELETE FROM worker_heartbeats"))
    assert await health_service.is_ready(db) is False

    await Worker(db, "test").beat()
    assert await health_service.is_ready(db) is True

    async with db.system_transaction() as conn:
        await conn.execute(
            text("UPDATE worker_heartbeats SET seen_at = now() - interval '5 minutes'")
        )
    assert await health_service.is_ready(db) is False


async def test_worker_loop_stops_cleanly(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "POLL_INTERVAL", 0.05)
    worker = Worker(db, "test-loop")
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.2)
    worker.stop()
    await asyncio.wait_for(task, 5)


def test_backoff_grows_and_caps() -> None:
    assert backoff(1) == timedelta(seconds=10)
    assert backoff(2) == timedelta(seconds=20)
    assert backoff(30) == timedelta(hours=1)
