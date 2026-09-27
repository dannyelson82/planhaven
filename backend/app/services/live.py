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


# Open WebSockets (collaboration + live updates) per user, so one account can't exhaust the
# server's connections (SECURITY.md §7.15).
MAX_SOCKETS_PER_USER = 20
_open_sockets: dict[uuid.UUID, int] = defaultdict(int)


def claim_socket(user_id: uuid.UUID) -> bool:
    if _open_sockets[user_id] >= MAX_SOCKETS_PER_USER:
        return False
    _open_sockets[user_id] += 1
    return True


def release_socket(user_id: uuid.UUID) -> None:
    _open_sockets[user_id] -= 1
    if _open_sockets[user_id] <= 0:
        _open_sockets.pop(user_id, None)
