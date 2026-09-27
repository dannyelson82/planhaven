"""Serves the built frontend (ARCHITECTURE.md §5): hashed assets with long caching, and
`index.html` for every other non-API path so the single-page app can route itself.

Asset files are listed once, and requests are looked up by exact name in that list: no part of
a request is ever used to build a filesystem path. Registered last, so API routes match first.
"""

from functools import cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter()

_IMMUTABLE = "public, max-age=31536000, immutable"


@cache
def _assets(directory: str) -> dict[str, Path]:
    folder = Path(directory) / "assets"
    if not folder.is_dir():
        return {}
    return {p.name: p for p in folder.iterdir() if p.is_file() and not p.is_symlink()}


@cache
def _index(directory: str) -> Path | None:
    index = Path(directory) / "index.html"
    return index if index.is_file() else None


def _frontend_dir(request: Request) -> str:
    directory: str | None = request.app.state.settings.frontend_dir
    if not directory:
        raise HTTPException(404)
    return directory


@router.get("/assets/{file_path:path}", include_in_schema=False)
async def asset(file_path: str, request: Request) -> FileResponse:
    target = _assets(_frontend_dir(request)).get(file_path)
    if target is None:
        raise HTTPException(404)
    return FileResponse(target, headers={"Cache-Control": _IMMUTABLE})


@router.get("/{path:path}", include_in_schema=False)
async def app_shell(path: str, request: Request) -> FileResponse:
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404)
    index = _index(_frontend_dir(request))
    if index is None:
        raise HTTPException(404)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
