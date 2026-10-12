import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class APIError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(
            status_code,
            {"code": code, "message": message},
            headers={"WWW-Authenticate": "Bearer"} if status_code == 401 else None,
        )


def install_error_handlers(app: FastAPI):
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        detail = (
            error.detail
            if isinstance(error.detail, dict)
            else {"code": "request_error", "message": str(error.detail)}
        )
        return JSONResponse(
            status_code=error.status_code, content={"error": detail}, headers=error.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        fields = [
            {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Check the submitted fields.",
                    "fields": fields,
                }
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        logger.error("Unhandled API error (%s)", type(error).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "The request could not be completed.",
                }
            },
        )
