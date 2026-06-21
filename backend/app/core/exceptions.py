from typing import Any, Optional


class AppError(Exception):
    """Application-level error that can be safely returned to API clients."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 500,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class ConfigurationError(AppError):
    """Raised when required runtime configuration is missing or invalid."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(
            code="CONFIGURATION_ERROR",
            message=message,
            status_code=500,
            details=details,
        )
