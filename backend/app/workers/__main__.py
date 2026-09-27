"""Worker process entry point: `python -m app.workers` (the container's `worker` service)."""

import asyncio
import signal

from app.core.config import load_settings
from app.core.logging import configure_logging
from app.db.database import Database
from app.workers.runner import Worker, new_worker_id


async def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    db = Database(settings)
    worker = Worker(db, new_worker_id())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker.stop)
    try:
        await worker.run()
    finally:
        await db.dispose()


if __name__ == "__main__":
    asyncio.run(main())
