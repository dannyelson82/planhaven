"""Application factory. Run with `uvicorn --factory app.main:create_app`."""

from fastapi import FastAPI

from app.api import health
from app.api.errors import install_error_handlers
from app.core.config import Settings, load_settings
from app.core.http import (
    AccessLogMiddleware,
    BodySizeLimitMiddleware,
    ProxyHeadersMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    UnhandledErrorMiddleware,
)
from app.core.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level)

    # Interactive docs and the OpenAPI schema are not served: they map the attack surface for
    # anyone on the internet. The schema is generated in CI instead (ARCHITECTURE.md §8.2).
    app = FastAPI(title="Planhaven", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    install_error_handlers(app)
    app.include_router(health.router)

    # add_middleware wraps from the inside out: the last one added is the outermost.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_json_bytes)
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(ProxyHeadersMiddleware, settings=settings)
    app.add_middleware(RequestIDMiddleware)
    return app
