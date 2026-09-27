"""Health endpoints (ARCHITECTURE.md §4.6). They never reveal version or configuration."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """Liveness: the process is up and serving requests."""
    return {"status": "ok"}
