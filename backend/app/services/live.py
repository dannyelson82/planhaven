"""In-process change notifications for live updates (ADR 0011).

Services publish "something in this project changed" after committing; browser connections
subscribed to that project are told to refresh. Only the kind of change is sent, never content.
Single-process: if the app ever runs several processes, this becomes PostgreSQL LISTEN/NOTIFY.
"""

import asyncio
import uuid
from collections import defaultdict

_subscribers: dict[uuid.UUID, set[asyncio.Queue[str]]] = defaultdict(set)


def publish(project_id: uuid.UUID, kind: str) -> None:
    for queue in list(_subscribers.get(project_id, ())):
        if queue.qsize() < 100:
            queue.put_nowait(kind)


def subscribe(project_id: uuid.UUID) -> asyncio.Queue[str]:
    queue: asyncio.Queue[str] = asyncio.Queue()
    _subscribers[project_id].add(queue)
    return queue


def unsubscribe(project_id: uuid.UUID, queue: asyncio.Queue[str]) -> None:
    _subscribers[project_id].discard(queue)
    if not _subscribers[project_id]:
        _subscribers.pop(project_id, None)
