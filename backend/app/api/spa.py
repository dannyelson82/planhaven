"""Serves the built frontend (ARCHITECTURE.md §5): hashed assets with long caching, and
`index.html` for every other non-API path so the single-page app can route itself.

Registered last, so every API route matches first."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter()

_IMMUTABLE = "public, max-age=31536000, immutable"


def _dist(request: Request) -> Path:
    directory = request.app.state.settings.frontend_dir
    if not directory:
        raise HTTPException(404)
    return Path(directory)


@router.get("/assets/{file_path:path}", include_in_schema=False)
async def asset(file_path: str, request: Request) -> FileResponse:
    root = (_dist(request) / "assets").resolve()
    target = (root / file_path).resolve()
    # Refuse anything outside the assets folder (../ tricks, symlinks) or missing.
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target, headers={"Cache-Control": _IMMUTABLE})


@router.get("/{path:path}", include_in_schema=False)
async def app_shell(path: str, request: Request) -> FileResponse:
    if path.startswith("api/") or path == "api":
        raise HTTPException(404)
    index = _dist(request) / "index.html"
    if not index.is_file():
        raise HTTPException(404)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
