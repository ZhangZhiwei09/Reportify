"""Stable API error model.

The wire format mirrors ``docs/architecture/07-api-and-ui.md`` §3.1: a problem
document carrying a stable ``code`` the UI can branch on, plus ``retryable``.
"""

from __future__ import annotations

from typing import Any

ERROR_TYPES: dict[str, str] = {
    "invalid_argument": "https://reportify.local/errors/invalid-argument",
    "unauthorized": "https://reportify.local/errors/unauthorized",
    "forbidden": "https://reportify.local/errors/forbidden",
    "not_found": "https://reportify.local/errors/not-found",
    "conflict": "https://reportify.local/errors/conflict",
    "conversation_busy": "https://reportify.local/errors/conversation-busy",
    "validation_failed": "https://reportify.local/errors/validation-failed",
    "rate_limited": "https://reportify.local/errors/rate-limited",
    "dependency_unavailable": "https://reportify.local/errors/dependency-unavailable",
    "model_not_configured": "https://reportify.local/errors/model-not-configured",
    "internal_error": "https://reportify.local/errors/internal-error",
}

ERROR_TITLES: dict[str, str] = {
    "invalid_argument": "Invalid argument",
    "unauthorized": "Unauthorized",
    "forbidden": "Forbidden",
    "not_found": "Not found",
    "conflict": "Conflict",
    "conversation_busy": "Conversation is busy",
    "validation_failed": "Validation failed",
    "rate_limited": "Rate limited",
    "dependency_unavailable": "Dependency unavailable",
    "model_not_configured": "Model is not configured",
    "internal_error": "Internal error",
}

DEFAULT_STATUS: dict[str, int] = {
    "invalid_argument": 400,
    "unauthorized": 401,
    "forbidden": 403,
    "not_found": 404,
    "conflict": 409,
    "conversation_busy": 409,
    "validation_failed": 422,
    "rate_limited": 429,
    "dependency_unavailable": 503,
    "model_not_configured": 503,
    "internal_error": 500,
}


class ApiError(Exception):
    """A domain error that maps onto the stable HTTP error model."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code or DEFAULT_STATUS.get(code, 500)
        self.retryable = retryable
        self.extra = extra or {}

    def body(self, instance: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": ERROR_TYPES.get(self.code, ERROR_TYPES["internal_error"]),
            "title": ERROR_TITLES.get(self.code, "Error"),
            "status": self.status_code,
            "code": self.code,
            "detail": self.detail,
            "retryable": self.retryable,
        }
        if instance is not None:
            payload["instance"] = instance
        if self.extra:
            payload["meta"] = self.extra
        return payload

    def __repr__(self) -> str:
        return f"ApiError(code={self.code!r}, status={self.status_code})"


class NotFound(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__("not_found", detail)


class InvalidArgument(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__("invalid_argument", detail)


class Conflict(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__("conflict", detail)


class ConversationBusy(ApiError):
    def __init__(self, detail: str = "Conversation already has an active run.") -> None:
        super().__init__("conversation_busy", detail)


class ValidationFailed(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__("validation_failed", detail)


class DependencyUnavailable(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__("dependency_unavailable", detail, retryable=True)


class ModelNotConfigured(ApiError):
    def __init__(self, detail: str = "REPORTIFY_DEEPSEEK_API_KEY is not set.") -> None:
        super().__init__("model_not_configured", detail)
