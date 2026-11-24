"""Shared pieces of the AI tools (A§12.3, ADR 0019, 0020): argument checks, the plan/done
records of a write, and finding a thing's project so `local_ai_only` projects stay invisible.

Argument checks are explicit, with limits, like the API's Pydantic models: tool arguments come
from an AI app and are untrusted.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app import authz
from app.db.database import Database
from app.services import projects as project_service
from app.services.auth import CurrentSession

STAGES = ("idea", "planning", "ready", "in_progress", "done", "archived")
MAX_CENTS = 100_000_000_000


class ToolError(ValueError):
    """Told to the AI app as a tool error (isError), in plain words, with a stable `code` and
    the argument at fault (if any) so an AI app (and whoever builds one) can tell why."""

    def __init__(self, message: str, *, code: str = "invalid_argument", field: str | None = None):
        super().__init__(message)
        self.code = code
        self.field = field


@dataclass(frozen=True, slots=True)
class Plan:
    """A write, checked and described, ready to apply or to wait for approval."""

    tool: str
    project_id: uuid.UUID | None
    arguments: dict[str, Any]
    summary: str


@dataclass(frozen=True, slots=True)
class Done:
    result: dict[str, Any]
    kind: str
    undo: dict[str, Any]


def text_arg(args: dict[str, Any], key: str, limit: int, *, required: bool = True) -> str:
    value = args.get(key)
    if value is None:
        if required:
            raise ToolError(f"'{key}' is required.", field=key)
        return ""
    if not isinstance(value, str):
        raise ToolError(f"'{key}' must be text.", field=key)
    value = value.strip()
    if required and not value:
        raise ToolError(f"'{key}' can't be empty.", field=key)
    if len(value) > limit:
        raise ToolError(f"'{key}' is longer than {limit} characters.", field=key)
    return value


def id_arg(args: dict[str, Any], key: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(args.get(key, "")))
    except ValueError:
        raise ToolError(f"'{key}' must be an id from PlanHaven.", field=key) from None


def optional_id(args: dict[str, Any], key: str) -> uuid.UUID | None:
    return None if args.get(key) is None else id_arg(args, key)


def choice_arg(args: dict[str, Any], key: str, options: tuple[str, ...]) -> str:
    value = args.get(key)
    if value not in options:
        raise ToolError(f"'{key}' is one of: {', '.join(options)}.", field=key)
    return str(value)


def bool_arg(args: dict[str, Any], key: str) -> bool:
    value = args.get(key)
    if not isinstance(value, bool):
        raise ToolError(f"'{key}' is true or false.", field=key)
    return value


def date_arg(args: dict[str, Any], key: str) -> str:
    """A YYYY-MM-DD date, kept as text (plans are stored as JSON)."""
    value = text_arg(args, key, 10)
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise ToolError(f"'{key}' is YYYY-MM-DD.", field=key) from None
    if not date(1900, 1, 1) <= day <= date(2200, 12, 31):
        raise ToolError(f"'{key}' is out of range.", field=key)
    return value


def number_arg(
    args: dict[str, Any], key: str, *, low: Decimal, high: Decimal, places: int, above: bool = False
) -> str:
    """A non-negative number, kept as text so it survives JSON exactly."""
    try:
        value = Decimal(str(args.get(key)))
    except InvalidOperation:
        raise ToolError(f"'{key}' is a number.", field=key) from None
    if not value.is_finite() or value < low or value > high or (above and value == low):
        raise ToolError(f"'{key}' is out of range.", field=key)
    if value != round(value, places):
        raise ToolError(f"'{key}' has at most {places} decimal places.", field=key)
    return str(value)


def money_arg(args: dict[str, Any], key: str, *, negative: bool = False) -> int:
    """An amount in the currency's units (12.34) as cents."""
    try:
        value = Decimal(str(args.get(key)))
    except InvalidOperation:
        raise ToolError(f"'{key}' is an amount like 12.34.", field=key) from None
    cents = value * 100
    if not value.is_finite() or cents != cents.to_integral_value():
        raise ToolError(f"'{key}' is an amount like 12.34.", field=key)
    if not (-MAX_CENTS if negative else 0) <= cents <= MAX_CENTS:
        raise ToolError(f"'{key}' is out of range.", field=key)
    return int(cents)


def given(args: dict[str, Any], *keys: str) -> list[str]:
    """The keys the AI app actually sent (null counts as sent: it clears)."""
    return [k for k in keys if k in args]


def names(texts: list[str]) -> str:
    return ", ".join(texts[:5]) + ("…" if len(texts) > 5 else "")


async def project(db: Database, session: CurrentSession, project_id: uuid.UUID) -> Any:
    """A project the connection may see: never one marked local_ai_only."""
    row = await project_service.get_project(db, session, project_id)
    if row.local_ai_only:
        raise authz.NotFoundError("Not found.")
    return row


async def editable(db: Database, session: CurrentSession, project_id: uuid.UUID) -> Any:
    """A visible project the person may change (owner or editor)."""
    row = await project(db, session, project_id)
    authz.require(session.principal, authz.Action.PROJECT_EDIT, authz.ProjectAccess(row.role))
    return row
