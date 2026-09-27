"""Job handlers by kind. Handlers register at import time with `@job("kind")`."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.database import Database


@dataclass(frozen=True, slots=True)
class JobContext:
    """What a handler gets. The only way to reach the database is `transaction()`, which acts
    as the user who enqueued the job (or system context for system jobs): a handler can't pick
    a different identity."""

    job_id: uuid.UUID
    user_id: uuid.UUID | None
    attempt: int
    _db: Database

    def transaction(self) -> AbstractAsyncContextManager[AsyncConnection]:
        if self.user_id is None:
            return self._db.system_transaction()
        return self._db.user_transaction(self.user_id)


type Handler = Callable[[JobContext, dict[str, Any]], Awaitable[None]]

_handlers: dict[str, Handler] = {}


def job(kind: str) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        if kind in _handlers:
            raise ValueError(f"duplicate job kind: {kind}")
        _handlers[kind] = handler
        return handler

    return register


def get_handler(kind: str) -> Handler | None:
    return _handlers.get(kind)


@asynccontextmanager
async def registered(kind: str, handler: Handler) -> AsyncIterator[None]:
    """Temporarily register a handler (tests)."""
    _handlers[kind] = handler
    try:
        yield
    finally:
        _handlers.pop(kind, None)
