"""Health endpoints (ARCHITECTURE.md §4.6). They never reveal version or configuration."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services import health as health_service

router = APIRouter()


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """Liveness: the process is up and serving requests."""
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz() -> JSONResponse:
    """Readiness: dependencies are reachable. Says nothing about which one failed."""
    if await health_service.is_ready():
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "not ready"}, status_code=503)
