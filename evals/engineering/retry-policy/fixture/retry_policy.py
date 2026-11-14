"""Retry delay policy used by the existing HTTP worker."""

BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 30.0


def retry_delay(attempt, retry_after=None):
    if retry_after:
        try:
            return min(float(retry_after), MAX_DELAY_SECONDS)
        except (TypeError, ValueError):
            pass
    return min(BASE_DELAY_SECONDS * (2 ** attempt), MAX_DELAY_SECONDS)
