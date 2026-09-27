"""Application factory. Run with `uvicorn --factory app.main:create_app`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api import (
    admin,
    auth,
    health,
    invites,
    lists,
    mfa,
    notes,
    notifications,
    passkeys,
    projects,
    sharing,
    spa,
)
from app.api.errors import install_error_handlers
from app.auth.session_keys import SessionKey
from app.core import security_log
from app.core.config import Settings, load_settings
from app.core.crypto import Keyring
from app.core.http import (
    AccessLogMiddleware,
    BodySizeLimitMiddleware,
    ProxyHeadersMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    UnhandledErrorMiddleware,
)
from app.core.logging import configure_logging
from app.db.database import Database
from app.plugins_host.host import LoadedPlugins, discover
from app.services import plugins as plugin_service

# Every router the app serves. The authorization test matrix reads this list, so a router
# can't be added without its routes being classified and tested (SECURITY.md §7.4).
ROUTERS = (
    health.router,
    auth.router,
    mfa.router,
    passkeys.router,
    invites.router,
    admin.router,
    notifications.router,
    projects.router,
    sharing.router,
    lists.router,
    notes.router,
    spa.router,  # last: catches every path the API didn't
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level)
    security_log.configure(settings.log_dir)

    # Interactive docs and the OpenAPI schema are not served: they map the attack surface for
    # anyone on the internet. The schema is generated in CI instead (ARCHITECTURE.md §8.2).
    db = Database(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Only admin-enabled plugins are imported (ARCHITECTURE.md §14.7).
        try:
            application.state.plugins = await plugin_service.load_enabled(
                db, application.state.plugins_discovered
            )
        except Exception:  # database not ready: start without plugins, /readyz will say so
            application.state.plugins = LoadedPlugins()
        yield
        await db.dispose()

    app = FastAPI(
        title="Planhaven", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.settings = settings
    app.state.db = db
    app.state.plugins_discovered = discover(settings.plugin_dirs)
    app.state.plugins = LoadedPlugins()
    app.state.session_key = SessionKey.from_dir(settings.secrets_dir)
    app.state.keyring = Keyring.from_file(Path(settings.secrets_dir) / "master.key")
    install_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router)

    # add_middleware wraps from the inside out: the last one added is the outermost.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_json_bytes)
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(ProxyHeadersMiddleware, settings=settings)
    app.add_middleware(RequestIDMiddleware)
    return app
