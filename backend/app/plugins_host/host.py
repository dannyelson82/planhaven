"""Plugin discovery, loading and the PluginContext implementation (ARCHITECTURE.md §14, ADR 0008).

- Discovery reads each `plugin.toml` under the plugin directories; nothing is imported.
- Only plugins an admin has enabled are imported (importing runs their code), and only if they
  target a supported API version. Changes take effect at the next restart.
- `HostPluginContext` enforces the manifest's permissions, then acts as the user through a
  user transaction, so RLS applies to plugin reads and writes too.
"""

import importlib
import json
import logging
import sys
import tomllib
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from planhaven_sdk import (
    API_VERSION,
    EventHandler,
    Manifest,
    PluginError,
    ProjectInfo,
    Scope,
)
from pydantic import ValidationError

from app.db import plugins as store
from app.db import projects as project_store
from app.db.database import Database

log = logging.getLogger("planhaven.plugins")

MAX_MANIFEST_BYTES = 64 * 1024
MAX_VALUE_BYTES = 64 * 1024
SUPPORTED_API_VERSIONS = frozenset({API_VERSION})


@dataclass(frozen=True, slots=True)
class DiscoveredPlugin:
    directory: Path
    manifest: Manifest | None
    error: str | None = None

    @property
    def plugin_id(self) -> str:
        return self.manifest.plugin.id if self.manifest else self.directory.name

    @property
    def compatible(self) -> bool:
        return (
            self.manifest is not None and self.manifest.plugin.api_version in SUPPORTED_API_VERSIONS
        )


def discover(directories: tuple[str, ...]) -> list[DiscoveredPlugin]:
    """Read manifests only. Later directories don't override earlier ones (bundled wins)."""
    found: dict[str, DiscoveredPlugin] = {}
    for base in directories:
        root = Path(base)
        if not root.is_dir():
            continue
        for directory in sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink()):
            manifest_path = directory / "plugin.toml"
            if not manifest_path.is_file():
                continue
            plugin = _read(directory, manifest_path)
            found.setdefault(plugin.plugin_id, plugin)
    return list(found.values())


def _read(directory: Path, path: Path) -> DiscoveredPlugin:
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            raise ValueError("plugin.toml is too large")
        manifest = Manifest.model_validate(tomllib.loads(path.read_text("utf-8")))
    except (OSError, ValueError, tomllib.TOMLDecodeError, ValidationError) as exc:
        return DiscoveredPlugin(directory, None, f"invalid plugin.toml ({type(exc).__name__})")
    if manifest.plugin.api_version not in SUPPORTED_API_VERSIONS:
        return DiscoveredPlugin(directory, manifest, "unsupported api_version")
    return DiscoveredPlugin(directory, manifest)


@dataclass
class LoadedPlugins:
    manifests: dict[str, Manifest] = field(default_factory=dict)
    handlers: dict[str, list[tuple[str, EventHandler]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    errors: dict[str, str] = field(default_factory=dict)


class _Registry:
    def __init__(self, manifest: Manifest, loaded: LoadedPlugins) -> None:
        self._manifest = manifest
        self._loaded = loaded

    def on_event(self, event_type: str, handler: EventHandler) -> None:
        if event_type not in self._manifest.permissions.events:
            raise PluginError(f"event {event_type!r} not declared in plugin.toml")
        self._loaded.handlers[event_type].append((self._manifest.plugin.id, handler))


def _entrypoint(directory: Path, spec: str) -> Any:
    """Import `package.module:function` from the plugin's own directory, and nowhere else: a
    manifest can't point at other installed code (e.g. `os:system`)."""
    module_name, func_name = spec.split(":")
    top = module_name.split(".")[0]
    if not ((directory / top).is_dir() or (directory / f"{top}.py").is_file()):
        raise PluginError("entrypoint must be code inside the plugin's directory")
    if str(directory) not in sys.path:
        sys.path.append(str(directory))
    # Dynamic import is the purpose of a plugin loader. Only admin-enabled plugins reach
    # here, the module must live in the plugin's directory (checked above and below).
    module = importlib.import_module(  # nosemgrep  (reviewed: see comment above)
        module_name
    )
    origin = Path(getattr(module, "__file__", "") or "").resolve()
    if not origin.is_relative_to(directory.resolve()):
        raise PluginError("entrypoint resolved outside the plugin's directory")
    return getattr(module, func_name)


def load(discovered: list[DiscoveredPlugin], enabled: set[str]) -> LoadedPlugins:
    loaded = LoadedPlugins()
    for plugin in discovered:
        if plugin.plugin_id not in enabled:
            continue
        if not plugin.compatible or plugin.manifest is None:
            loaded.errors[plugin.plugin_id] = plugin.error or "incompatible"
            continue
        manifest = plugin.manifest
        try:
            if manifest.entrypoints.backend:
                register = _entrypoint(plugin.directory, manifest.entrypoints.backend)
                register(_Registry(manifest, loaded))
            loaded.manifests[manifest.plugin.id] = manifest
            log.info("plugin loaded", extra={"plugin_id": manifest.plugin.id})
        except Exception as exc:  # a broken plugin must not stop Planhaven starting
            loaded.errors[manifest.plugin.id] = f"failed to load ({type(exc).__name__})"
            log.error(
                "plugin failed to load",
                extra={"plugin_id": manifest.plugin.id, "error": type(exc).__name__},
            )
    return loaded


class HostPluginContext:
    """The PluginContext given to a plugin, acting for one user."""

    def __init__(self, db: Database, manifest: Manifest, user_id: uuid.UUID) -> None:
        self._db = db
        self._manifest = manifest
        self._user_id = user_id

    @property
    def plugin_id(self) -> str:
        return self._manifest.plugin.id

    @property
    def user_id(self) -> uuid.UUID:
        return self._user_id

    def _need(self, allowed: list[str], what: str, access: str) -> None:
        if access not in allowed:
            raise PluginError(f"plugin {self.plugin_id!r} lacks {what}:{access} permission")

    async def get_project(self, project_id: uuid.UUID) -> ProjectInfo | None:
        self._need(list(self._manifest.permissions.projects), "projects", "read")
        async with self._db.user_transaction(self._user_id) as conn:
            row = await project_store.get_project(conn, project_id)
        if row is None or row.role is None:
            return None
        return ProjectInfo(id=row.id, title=row.title, stage=row.stage, role=row.role)  # type: ignore[arg-type]

    def _scope_permissions(self, scope: Scope) -> list[str]:
        perms = self._manifest.permissions
        return list(perms.project_data if scope == "project" else perms.user_data)

    async def get_data(self, scope: Scope, scope_id: uuid.UUID, key: str) -> Any | None:
        self._need(self._scope_permissions(scope), f"{scope}_data", "read")
        async with self._db.user_transaction(self._user_id) as conn:
            return await store.get_data(conn, self.plugin_id, scope, scope_id, key)

    async def put_data(self, scope: Scope, scope_id: uuid.UUID, key: str, value: Any) -> None:
        self._need(self._scope_permissions(scope), f"{scope}_data", "write")
        if not 1 <= len(key) <= 100:
            raise PluginError("key must be 1-100 characters")
        if len(json.dumps(value).encode()) > MAX_VALUE_BYTES:
            raise PluginError("value too large (64 KB max)")
        async with self._db.user_transaction(self._user_id) as conn:
            await store.put_data(conn, self.plugin_id, scope, scope_id, key, value, self._user_id)
