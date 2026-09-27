"""RFC 9457 problem responses (ARCHITECTURE.md §8.2). No stack traces, internal IDs or echoed
input in responses: validation errors report where the problem is, not the submitted value.
Unexpected exceptions are handled by `app.core.http.UnhandledErrorMiddleware`."""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import authz
from app.services.limits import RateLimitedError

PROBLEM_JSON = "application/problem+json"


def problem(status: int, detail: str | None = None, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
    }
    if detail:
        body["detail"] = detail
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        return problem(500)
    # Only our own, deliberately written details are passed through; framework defaults
    # ("Not Found") duplicate the title and are dropped.
    detail = (
        exc.detail
        if isinstance(exc.detail, str) and exc.detail != HTTPStatus(exc.status_code).phrase
        else None
    )
    response = problem(exc.status_code, detail)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        return problem(500)
    errors = [
        {"loc": [str(part) for part in err.get("loc", ())], "type": err.get("type", "invalid")}
        for err in exc.errors()
    ][:50]
    return problem(422, "The request is not valid.", errors=errors)


async def _rate_limited(_: Request, exc: Exception) -> JSONResponse:
    retry_after = exc.retry_after if isinstance(exc, RateLimitedError) else 60
    response = problem(429, "Too many attempts. Try again later.")
    response.headers["Retry-After"] = str(max(1, retry_after))
    return response


async def _authz(_: Request, exc: Exception) -> JSONResponse:
    # Not-found over forbidden: a resource the principal can't know about is simply absent.
    if isinstance(exc, authz.NotFoundError):
        return problem(404)
    return problem(403, str(exc))


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(authz.AuthzError, _authz)
    app.add_exception_handler(RateLimitedError, _rate_limited)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
