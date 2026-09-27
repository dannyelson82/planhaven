"""Application factory."""

from fastapi import FastAPI

from app.api import health


def create_app() -> FastAPI:
    # Interactive docs and the OpenAPI schema are not served: they map the attack surface for
    # anyone on the internet. The schema is generated in CI instead (ARCHITECTURE.md §8.2).
    app = FastAPI(
        title="Planhaven",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(health.router)
    return app


app = create_app()
