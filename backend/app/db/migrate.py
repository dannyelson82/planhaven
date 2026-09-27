"""Apply database migrations as the table-owner role. Run by the container's `migrate`
service before the app starts: `python -m app.db.migrate`."""

import sys

from alembic import command

from app.db.migrations import alembic_config, head_revision


def main() -> int:
    command.upgrade(alembic_config(), "head")
    print(f"migrate: database at revision {head_revision()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
