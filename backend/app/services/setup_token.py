"""Print the one-time setup token at boot while no admin exists (SECURITY.md §7.1).
Run by the container's `setup-token` service: `python -m app.services.setup_token`."""

import asyncio
import sys

from app.core.config import load_settings
from app.db.database import Database
from app.services.auth import SETUP_TOKEN_TTL, issue_setup_token


async def _main() -> int:
    db = Database(load_settings())
    try:
        token = await issue_setup_token(db)
    finally:
        await db.dispose()
    if token is None:
        return 0
    hours = int(SETUP_TOKEN_TTL.total_seconds() // 3600)
    # Printed directly (not through the logger, which would redact it): the operator needs it.
    print(
        "\n"
        "==================================================================\n"
        " Planhaven setup: no admin account exists yet.\n"
        " Open Planhaven in your browser and enter this one-time token:\n\n"
        f"   {token}\n\n"
        f" It works once and expires in {hours} hours. Restart the container\n"
        " for a new one. Anyone with this token can create the admin account.\n"
        "==================================================================\n",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
