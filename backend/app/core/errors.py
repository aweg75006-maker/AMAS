from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError
from app.core.identity import DEFAULT_TENANT_ID, DEFAULT_USER_ID, RequestContext, clean_context_id
from app.core.logging import get_logger
from app.services.workflow_trace_service import safe_record_error_event


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


def context_from_request(request: Request) -> RequestContext:
    return RequestContext(
        tenant_id=clean_context_id(request.headers.get("X-Tenant-ID"), DEFAULT_TENANT_ID),
        user_id=clean_context_id(request.headers.get("X-User-ID"), DEFAULT_USER_ID),
        auth_source="headers",
    )


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
        await safe_record_error_event(
            error_code=exc.code,
            message=exc.message,
            source="api",
            severity="warning" if exc.status_code < 500 else "error",
            context=context_from_request(request),
            request_id=request_id,
            path=str(request.url.path),
            status_code=exc.status_code,
            details=exc.details,
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
        await safe_record_error_event(
            error_code=code,
            message=str(exc.detail),
            source="api",
            severity="warning" if exc.status_code < 500 else "error",
            context=context_from_request(request),
            request_id=request_id,
            path=str(request.url.path),
            status_code=exc.status_code,
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
        await safe_record_error_event(
            error_code="VALIDATION_ERROR",
            message="请求参数校验失败",
            source="api",
            severity="warning",
            context=context_from_request(request),
            request_id=request_id,
            path=str(request.url.path),
            status_code=422,
            details={"errors": exc.errors()},
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
        await safe_record_error_event(
            error_code="INTERNAL_ERROR",
            message=str(exc),
            source="api",
            severity="error",
            context=context_from_request(request),
            request_id=request_id,
            path=str(request.url.path),
            status_code=500,
        )
        return json_error_response(
            status_code=500,
            code="INTERNAL_ERROR",
            message="服务内部错误",
            request_id=request_id,
        )
