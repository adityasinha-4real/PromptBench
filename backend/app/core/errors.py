"""Error taxonomy shared by providers, services and the HTTP layer.

Every provider failure is normalised into a :class:`ProviderError` carrying an
:class:`ErrorCode`, so the UI can render an actionable message instead of a bare
HTTP status.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Stable, machine-readable failure categories."""

    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    AUTHENTICATION = "authentication"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_REQUEST = "invalid_request"
    CONTENT_FILTER = "content_filter"
    CANCELLED = "cancelled"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


#: Failure categories where retrying with backoff is reasonable.
RETRYABLE_CODES: frozenset[ErrorCode] = frozenset(
    {ErrorCode.TIMEOUT, ErrorCode.RATE_LIMIT, ErrorCode.PROVIDER_UNAVAILABLE}
)

_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.TIMEOUT: 504,
    ErrorCode.RATE_LIMIT: 429,
    ErrorCode.AUTHENTICATION: 401,
    ErrorCode.PROVIDER_UNAVAILABLE: 503,
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.CONTENT_FILTER: 422,
    ErrorCode.CANCELLED: 499,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.UNKNOWN: 500,
}

_HINT_BY_CODE: dict[ErrorCode, str] = {
    ErrorCode.TIMEOUT: "The provider did not respond in time. Try again or raise the timeout.",
    ErrorCode.RATE_LIMIT: "The provider is rate limiting this key. Wait a moment and retry.",
    ErrorCode.AUTHENTICATION: (
        "Check that the provider's API key environment variable is set and valid."
    ),
    ErrorCode.PROVIDER_UNAVAILABLE: (
        "The provider could not be reached. Check connectivity or the base URL."
    ),
    ErrorCode.INVALID_REQUEST: (
        "The request was rejected. Check the model name and generation parameters."
    ),
    ErrorCode.CONTENT_FILTER: (
        "The provider blocked this prompt or response under its safety policy."
    ),
    ErrorCode.CANCELLED: "The run was cancelled before this model finished.",
}


class PromptBenchError(Exception):
    """Base class for all application errors."""

    code: ErrorCode = ErrorCode.UNKNOWN

    def __init__(self, message: str, *, code: ErrorCode | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    @property
    def status_code(self) -> int:
        return _STATUS_BY_CODE.get(self.code, 500)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": str(self.code), "message": self.message}
        hint = _HINT_BY_CODE.get(self.code)
        if hint:
            payload["hint"] = hint
        return payload


class ProviderError(PromptBenchError):
    """A normalised provider failure.

    Attributes:
        provider: Provider id that produced the failure.
        model: Model id that was requested, when known.
        retryable: Whether the benchmark engine may retry this call.
        status_code_upstream: HTTP status returned by the provider, when known.
    """

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode = ErrorCode.UNKNOWN,
        provider: str | None = None,
        model: str | None = None,
        retryable: bool | None = None,
        status_code_upstream: int | None = None,
    ) -> None:
        super().__init__(message, code=code)
        self.provider = provider
        self.model = model
        self.retryable = code in RETRYABLE_CODES if retryable is None else retryable
        self.status_code_upstream = status_code_upstream

    def display_message(self) -> str:
        """Human-facing one-liner, e.g. ``Gemini request failed: API key is missing.``"""
        label = (self.provider or "Provider").replace("_", " ").title()
        return f"{label} request failed: {self.message}"

    def to_payload(self) -> dict[str, Any]:
        payload = super().to_payload()
        payload.update(
            {
                "provider": self.provider,
                "model": self.model,
                "retryable": self.retryable,
                "upstream_status": self.status_code_upstream,
            }
        )
        return payload


class NotFoundError(PromptBenchError):
    code = ErrorCode.NOT_FOUND


class ValidationError(PromptBenchError):
    code = ErrorCode.INVALID_REQUEST


class ConflictError(PromptBenchError):
    code = ErrorCode.CONFLICT


def classify_http_status(status: int, body: str = "") -> ErrorCode:
    """Map an upstream HTTP status (plus body hints) onto an :class:`ErrorCode`."""
    lowered = body.lower()
    if status in (401, 403):
        return ErrorCode.AUTHENTICATION
    if status == 429:
        return ErrorCode.RATE_LIMIT
    if status == 404:
        # A 404 from a provider almost always means "unknown model".
        return ErrorCode.INVALID_REQUEST
    if status in (408, 504):
        return ErrorCode.TIMEOUT
    if status in (502, 503, 529):
        return ErrorCode.PROVIDER_UNAVAILABLE
    if 400 <= status < 500:
        if "safety" in lowered or ("content" in lowered and "filter" in lowered):
            return ErrorCode.CONTENT_FILTER
        return ErrorCode.INVALID_REQUEST
    if status >= 500:
        return ErrorCode.PROVIDER_UNAVAILABLE
    return ErrorCode.UNKNOWN
