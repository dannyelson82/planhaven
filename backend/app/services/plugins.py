"""Plugin administration (ARCHITECTURE.md §14.7): list what's installed, enable or disable.
Admin-only; enabling takes effect at the next restart."""

from dataclasses import dataclass

from app import authz
from app.core import security_log
from app.db import auth as audit
from app.db import plugins as store
from app.db.database import Database
from app.plugins_host.host import DiscoveredPlugin, LoadedPlugins, load
from app.services.auth import CurrentSession


@dataclass(frozen=True, slots=True)
class PluginInfo:
    id: str
    name: str | None
    version: str | None
    description: str | None
    permissions: dict[str, object] | None
    compatible: bool
    error: str | None
    enabled: bool
    loaded: bool


async def list_plugins(
    db: Database,
    session: CurrentSession,
    discovered: list[DiscoveredPlugin],
    loaded: LoadedPlugins,
) -> list[PluginInfo]:
    authz.require(session.principal, authz.Action.ADMIN)
    async with db.system_transaction() as conn:
        enabled = await store.enabled_ids(conn)
    out = []
    for p in discovered:
        m = p.manifest
        out.append(
            PluginInfo(
                id=p.plugin_id,
                name=m.plugin.name if m else None,
                version=m.plugin.version if m else None,
                description=m.plugin.description if m else None,
                permissions=m.permissions.model_dump() if m else None,
                compatible=p.compatible,
                error=p.error or loaded.errors.get(p.plugin_id),
                enabled=p.plugin_id in enabled,
                loaded=p.plugin_id in loaded.manifests,
            )
        )
    return out


async def set_enabled(
    db: Database,
    session: CurrentSession,
    discovered: list[DiscoveredPlugin],
    plugin_id: str,
    enabled: bool,
    ip: str | None,
) -> None:
    authz.require(session.principal, authz.Action.ADMIN)
    plugin = next((p for p in discovered if p.plugin_id == plugin_id), None)
    if plugin is None:
        raise authz.NotFoundError("Not found.")
    if enabled and not plugin.compatible:
        raise ValueError("This plugin isn't compatible with this version of PlanHaven.")
    async with db.system_transaction() as conn:
        await store.set_enabled(conn, plugin_id, enabled, session.user.id)
        await audit.record_audit(
            conn,
            action="plugin.enabled" if enabled else "plugin.disabled",
            actor_user_id=session.user.id,
            ip=ip,
            resource_type="plugin",
        )
    security_log.event(
        "plugin_enabled" if enabled else "plugin_disabled",
        ip=ip,
        user_id=session.user.id,
        plugin_id=plugin_id,
    )


async def load_enabled(db: Database, discovered: list[DiscoveredPlugin]) -> LoadedPlugins:
    async with db.system_transaction() as conn:
        enabled = await store.enabled_ids(conn)
    return load(discovered, enabled)
