"""The MCP endpoint (A§12.1): `POST /mcp` with an AI app's access token. Stateless JSON
responses; no server-sent events (GET is refused)."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.api import deps
from app.services import mcp as service

router = APIRouter()
McpToken = Annotated[Any, Depends(deps.require_mcp_token)]


@router.post("/mcp", include_in_schema=False)
async def mcp(connection: McpToken, request: Request) -> Response:
    # DNS-rebinding defence (MCP spec): a browser page from elsewhere can't use /mcp.
    origin = request.headers.get("origin")
    if origin is not None and origin != deps.settings(request).base_origin:
        raise HTTPException(403, "Cross-origin request refused.")
    try:
        message = json.loads(await request.body())
    except ValueError:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status_code=400,
        )
    reply = await service.handle(
        deps.database(request), connection, message, version=deps.settings(request).version
    )
    if reply is None:
        return Response(status_code=202)
    return JSONResponse(reply, headers={"Cache-Control": "no-store"})


@router.get("/mcp", include_in_schema=False)
@router.delete("/mcp", include_in_schema=False)
async def mcp_other() -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})
