"""Stable, safe-to-display errors used by Analytics adapters and the BFF."""


class AnalyticsError(Exception):
    """An expected Analytics failure with a stable machine-readable code."""

    code = "ANALYTICS_ERROR"
    retryable = False

    def __init__(self, message: str, *, code: str | None = None,
                 retryable: bool | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code
        if retryable is not None:
            self.retryable = retryable


class ValidationError(AnalyticsError):
    code = "INVALID_REQUEST"


class UnavailableError(AnalyticsError):
    code = "UNAVAILABLE"
    retryable = True


class ConflictError(AnalyticsError):
    code = "CONFLICT"


class NotFoundError(AnalyticsError):
    code = "NOT_FOUND"


class IntegrityError(AnalyticsError):
    code = "INTEGRITY_ERROR"


class ProviderError(AnalyticsError):
    code = "PROVIDER_ERROR"
    retryable = True


class CoverageError(AnalyticsError):
    code = "LOCAL_COVERAGE_MISMATCH"


class ReadOnlyError(ValidationError):
    code = "READ_ONLY_QUERY_REQUIRED"
