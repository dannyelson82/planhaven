"""Locating Alembic migrations and the revision this code expects."""

from functools import cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

# Shipped inside the package so the installed app always carries its own migrations.
MIGRATIONS_DIR = Path(__file__).resolve().parent / "schema_migrations"


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


@cache
def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()
