"""Planhaven plugin SDK, API version 1 (ARCHITECTURE.md §14).

Plugins interact with Planhaven only through the `PluginContext` they are given: async
methods taking and returning plain, serializable data. Plugins import nothing from the
Planhaven application itself (enforced by tests), so this interface can later be served over
RPC from an isolated process without changing plugins (ADR 0008).
"""

import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

API_VERSION = "1"

PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_]{1,39}$")

Scope = Literal["project", "user"]


class Permissions(BaseModel):
    """What a plugin asks to do. Shown to the admin before enabling; enforced by the host."""

    model_config = ConfigDict(extra="forbid")

    project_data: list[Literal["read", "write"]] = []
    user_data: list[Literal["read", "write"]] = []
    projects: list[Literal["read"]] = []
    events: list[str] = []


class Entrypoints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: str | None = Field(default=None, pattern=r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")
    ui: str | None = None


class PluginMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=40)
    api_version: str
    description: str = Field(default="", max_length=500)

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not PLUGIN_ID.match(value):
            raise ValueError("id must be lowercase letters, digits and _, starting with a letter")
        return value


class Manifest(BaseModel):
    """Parsed `plugin.toml`."""

    model_config = ConfigDict(extra="forbid")

    plugin: PluginMeta
    permissions: Permissions = Permissions()
    entrypoints: Entrypoints = Entrypoints()


class ProjectInfo(BaseModel):
    id: uuid.UUID
    title: str
    stage: str
    role: Literal["owner", "editor", "viewer"]


class Event(BaseModel):
    type: str
    project_id: uuid.UUID | None = None
    payload: dict[str, Any] = {}


class PluginContext(Protocol):
    """Everything a plugin can do. All methods act as the user the call is for, with that
    user's permissions, and within what the plugin's manifest was granted."""

    @property
    def plugin_id(self) -> str: ...

    @property
    def user_id(self) -> uuid.UUID: ...

    async def get_project(self, project_id: uuid.UUID) -> ProjectInfo | None: ...

    async def get_data(self, scope: Scope, scope_id: uuid.UUID, key: str) -> Any | None: ...

    async def put_data(self, scope: Scope, scope_id: uuid.UUID, key: str, value: Any) -> None: ...


EventHandler = Callable[[PluginContext, Event], Awaitable[None]]


class Registry(Protocol):
    """Passed to a plugin's backend entrypoint (`register(registry)`)."""

    def on_event(self, event_type: str, handler: EventHandler) -> None: ...


class PluginError(Exception):
    """A plugin asked for something outside its permissions or the API."""
