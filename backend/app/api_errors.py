import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.advisory_schemas import ErrorBody, ErrorOut

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        session_id: str | None = None,
    ):
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.session_id = session_id


def error_response(
    status_code: int,
    code: str,
    message: str,
    session_id: str | None = None,
    headers: dict[str, str] | None = None,
):
    body = ErrorOut(
        error=ErrorBody(
            code=code,
            message=message,
            session_id=session_id,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return error_response(
            exc.status_code,
            exc.code,
            exc.message,
            exc.session_id,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ):
        # Do not echo raw inputs, exception contexts, or applicant data.
        locations = [
            ".".join(str(part) for part in error["loc"])
            for error in exc.errors()[:12]
        ]
        return error_response(
            422,
            "VALIDATION_ERROR",
            "Invalid request fields: " + ", ".join(locations),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request,
        exc: StarletteHTTPException,
    ):
        message = (
            exc.detail
            if isinstance(exc.detail, str) and exc.status_code < 500
            else "Request could not be completed."
        )
        return error_response(
            exc.status_code,
            f"HTTP_{exc.status_code}",
            message,
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        logger.exception(
            "Unhandled API exception",
            exc_info=exc,
        )
        return error_response(
            500,
            "INTERNAL_ERROR",
            "An unexpected error occurred. Please try again.",
        )