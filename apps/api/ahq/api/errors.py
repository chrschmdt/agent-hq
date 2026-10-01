from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from ahq.domain import ConfigurationError, ConflictError, InvalidRequest, NotFoundError

PROBLEM_JSON = "application/problem+json"


def _problem(status_code: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        {"type": "about:blank", "title": title, "status": status_code, "detail": detail},
        status_code=status_code,
        media_type=PROBLEM_JSON,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def not_found(request: Request, error: NotFoundError) -> JSONResponse:
        return _problem(status.HTTP_404_NOT_FOUND, "Not found", str(error))

    @app.exception_handler(ConflictError)
    async def conflict(request: Request, error: ConflictError) -> JSONResponse:
        return _problem(status.HTTP_409_CONFLICT, "Conflict", str(error))

    @app.exception_handler(InvalidRequest)
    async def invalid(request: Request, error: InvalidRequest) -> JSONResponse:
        return _problem(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid request", str(error))

    @app.exception_handler(ConfigurationError)
    async def unavailable(request: Request, error: ConfigurationError) -> JSONResponse:
        return _problem(status.HTTP_503_SERVICE_UNAVAILABLE, "Not available here", str(error))
