"""Attachments: upload files and photos to a project, list, download, delete (A§10, S§7.5).

Uploads are the raw file as the request body (no multipart parser); the name comes from the
`filename` query parameter and is treated as display data only. Files are always downloaded
as attachments; only our own re-encoded images and thumbnails are shown inline.
"""

import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from app.api import deps
from app.api.deps import SessionDep
from app.core.http import FILE_CSP
from app.services import attachments as service

router = APIRouter(prefix="/api/v1", tags=["attachments"])


class AttachmentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    kind: str
    content_type: str
    size: int
    has_thumbnail: bool
    metadata_kept: bool
    created_at: datetime
    can_delete: bool = False


def _out(a: service.AttachmentRow, can_delete: bool = False) -> AttachmentOut:
    return AttachmentOut(
        id=a.id,
        project_id=a.project_id,
        filename=a.filename,
        kind=a.kind,
        content_type=a.content_type,
        size=a.size,
        has_thumbnail=a.thumb_sha256 is not None,
        metadata_kept=a.metadata_kept,
        created_at=a.created_at,
        can_delete=can_delete,
    )


def _file(
    request: Request, sha256: str, media_type: str, disposition: str, name: str
) -> FileResponse:
    ascii_name = name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
    return FileResponse(
        deps.blobs(request).path(sha256),
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
            ),
            "Content-Security-Policy": FILE_CSP,
            "Cache-Control": "private, max-age=300",
        },
    )


@router.get("/projects/{project_id}/attachments")
async def list_attachments(
    project_id: uuid.UUID, session: SessionDep, request: Request
) -> list[AttachmentOut]:
    rows = await service.attachments_for_project(deps.database(request), session, project_id)
    return [_out(a) for a in rows]


@router.post("/projects/{project_id}/attachments", status_code=201)
async def upload_attachment(
    project_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    keep_metadata: bool = False,
) -> AttachmentOut:
    try:
        row = await service.upload(
            deps.database(request),
            deps.blobs(request),
            session,
            project_id,
            filename=filename,
            keep_metadata=keep_metadata,
            chunks=request.stream(),
            max_bytes=deps.settings(request).max_upload_mb * 1024 * 1024,
            ip=deps.client_ip(request),
        )
    except service.UploadTooLargeError:
        raise HTTPException(413, "This file is larger than the upload limit.") from None
    except service.UnsupportedFileError as exc:
        raise HTTPException(415, str(exc)) from None
    return _out(row, can_delete=True)


@router.get("/attachments/{attachment_id}")
async def get_attachment(
    attachment_id: uuid.UUID, session: SessionDep, request: Request
) -> AttachmentOut:
    row, can_delete = await service.get_attachment(deps.database(request), session, attachment_id)
    return _out(row, can_delete)


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(
    attachment_id: uuid.UUID, session: SessionDep, request: Request
) -> FileResponse:
    row, _ = await service.get_attachment(deps.database(request), session, attachment_id)
    return _file(request, row.blob_sha256, "application/octet-stream", "attachment", row.filename)


@router.get("/attachments/{attachment_id}/view")
async def view_attachment(
    attachment_id: uuid.UUID, session: SessionDep, request: Request
) -> FileResponse:
    """Images we re-encoded ourselves, shown inline. Nothing else is ever inline."""
    row, _ = await service.get_attachment(deps.database(request), session, attachment_id)
    if row.kind != "image" or row.metadata_kept or row.thumb_sha256 is None:
        raise HTTPException(404, "No preview for this file.")
    return _file(request, row.blob_sha256, row.content_type, "inline", row.filename)


@router.get("/attachments/{attachment_id}/thumbnail")
async def attachment_thumbnail(
    attachment_id: uuid.UUID, session: SessionDep, request: Request
) -> FileResponse:
    row, _ = await service.get_attachment(deps.database(request), session, attachment_id)
    if row.thumb_sha256 is None:
        raise HTTPException(404, "No thumbnail for this file.")
    return _file(request, row.thumb_sha256, "image/webp", "inline", "thumbnail.webp")


@router.delete("/attachments/{attachment_id}", status_code=204)
async def delete_attachment(
    attachment_id: uuid.UUID, session: SessionDep, request: Request
) -> None:
    await service.delete_attachment(
        deps.database(request), session, attachment_id, deps.client_ip(request)
    )
