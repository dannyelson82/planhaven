"""Worker process entry point: `python -m app.workers` (the container's `worker` service)."""

import asyncio
import signal

from app.core.config import load_settings
from app.core.logging import configure_logging
from app.db.database import Database
from app.services import notifications
from app.services.attachments import BlobStore
from app.workers.runner import Worker, new_worker_id


async def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    db = Database(settings)
    # Phone alerts are signed with the VAPID key from first boot; the subject tells push
    # services who runs this server (RFC 8292).
    subject = settings.base_url if settings.base_scheme == "https" else "mailto:push@invalid"
    try:
        push = notifications.Sender.from_dir(settings.secrets_dir, subject)
    except OSError:
        push = None  # no key yet (source checkout): no phone alerts
    worker = Worker(db, new_worker_id(), BlobStore(settings.data_dir), push)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker.stop)
    try:
        await worker.run()
    finally:
        await db.dispose()


if __name__ == "__main__":
    asyncio.run(main())
