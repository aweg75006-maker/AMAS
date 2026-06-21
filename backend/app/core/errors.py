from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError
from app.core.logging import get_logger


logger = get_logger("iris.errors")


def error_payload(
    *,
    code: str,
    message: str,
    request_id: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "details": details or {},
        }
    }


def request_id_from(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def json_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_payload(
            code=code,
            message=message,
            request_id=request_id,
            details=details,
        ),
    )


def sse_error_event(
    *,
    code: str,
    message: str,
    request_id: str,
    details: dict[str, Any] | None = None,
) -> str:
    import json

    data = {
        "step": "__error__",
        "data": error_payload(
            code=code,
            message=message,
            request_id=request_id,
            details=details,
        )["error"],
    }
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        request_id = request_id_from(request)
        logger.warning(
            "application_error",
            extra={
                "request_id": request_id,
                "error_code": exc.code,
                "status_code": exc.status_code,
                "details": exc.details,
            },
        )
        return json_error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            request_id=request_id,
            details=exc.details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException):
        request_id = request_id_from(request)
        code = "HTTP_ERROR"
        if exc.status_code == 404:
            code = "NOT_FOUND"
        elif exc.status_code == 400:
            code = "BAD_REQUEST"

        logger.warning(
            "http_error",
            extra={
                "request_id": request_id,
                "error_code": code,
                "status_code": exc.status_code,
            },
        )
        return json_error_response(
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail),
            request_id=request_id,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        request_id = request_id_from(request)
        logger.warning(
            "validation_error",
            extra={
                "request_id": request_id,
                "error_code": "VALIDATION_ERROR",
                "status_code": 422,
            },
        )
        return json_error_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数校验失败",
            request_id=request_id,
            details={"errors": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        request_id = request_id_from(request)
        logger.exception(
            "unexpected_error",
            extra={
                "request_id": request_id,
                "error_code": "INTERNAL_ERROR",
                "status_code": 500,
            },
        )
        return json_error_response(
            status_code=500,
            code="INTERNAL_ERROR",
            message="服务内部错误",
            request_id=request_id,
        )
