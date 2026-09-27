"""The worker loop (ADR 0003): claim a job, run it as its user, record the outcome.

Failures retry with exponential backoff and become `dead` after max_attempts. Only the
exception *type* is stored and logged, since messages can contain user data. A job that
outlives its lease (e.g. the worker crashed) is picked up again by the next claim.
"""

import asyncio
import contextlib
import logging
import socket
import uuid
from datetime import timedelta

from app.db import jobs as job_store
from app.db.database import Database
from app.workers.registry import JobContext, get_handler

log = logging.getLogger("planhaven.worker")

JOB_TIMEOUT = timedelta(minutes=10)
LEASE = JOB_TIMEOUT + timedelta(minutes=1)
POLL_INTERVAL = 2.0
HEARTBEAT_INTERVAL = 10.0
BACKOFF_BASE = timedelta(seconds=10)
BACKOFF_MAX = timedelta(hours=1)


def backoff(attempt: int) -> timedelta:
    return min(BACKOFF_BASE * (1 << min(max(attempt - 1, 0), 20)), BACKOFF_MAX)


class Worker:
    def __init__(self, db: Database, worker_id: str | None = None) -> None:
        self.db = db
        self.worker_id = worker_id or new_worker_id()
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        """Finish the current job, then exit."""
        self._stopping.set()

    async def beat(self) -> None:
        async with self.db.system_transaction() as conn:
            await job_store.heartbeat(conn, self.worker_id)

    async def run_once(self) -> bool:
        """Claim and run one job. Returns False when nothing was due."""
        async with self.db.system_transaction() as conn:
            claimed = await job_store.claim(conn, LEASE)
        if claimed is None:
            return False

        handler = get_handler(claimed.kind)
        ctx = JobContext(claimed.id, claimed.user_id, claimed.attempts, self.db)
        try:
            if handler is None:
                raise LookupError("no handler for job kind")
            await asyncio.wait_for(handler(ctx, claimed.payload), JOB_TIMEOUT.total_seconds())
        except Exception as exc:
            error = type(exc).__name__
            final = handler is None or claimed.attempts >= claimed.max_attempts
            retry_in = None if final else backoff(claimed.attempts)
            async with self.db.system_transaction() as conn:
                await job_store.mark_failed(conn, claimed, error, retry_in)
            log.warning(
                "job failed",
                extra={
                    "job_id": str(claimed.id),
                    "kind": claimed.kind,
                    "attempt": claimed.attempts,
                    "error": error,
                    "dead": final,
                },
            )
            return True

        async with self.db.system_transaction() as conn:
            await job_store.mark_done(conn, claimed.id)
        log.info("job done", extra={"job_id": str(claimed.id), "kind": claimed.kind})
        return True

    async def run(self) -> None:
        log.info("worker started", extra={"worker_id": self.worker_id})
        last_beat = -HEARTBEAT_INTERVAL
        loop = asyncio.get_running_loop()
        while not self._stopping.is_set():
            try:
                if loop.time() - last_beat >= HEARTBEAT_INTERVAL:
                    await self.beat()
                    last_beat = loop.time()
                if await self.run_once():
                    continue
            except Exception as exc:  # database hiccup: log, wait, carry on
                log.error("worker loop error", extra={"error": type(exc).__name__})
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), POLL_INTERVAL)
        log.info("worker stopped", extra={"worker_id": self.worker_id})


def new_worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
