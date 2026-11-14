"""Pure Retry-After parsing and capped exponential backoff policy."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math

BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 30.0


def _valid_delay(value):
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, MAX_DELAY_SECONDS)


def _http_date_delay(value, now):
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        return None
    return _valid_delay((parsed - now).total_seconds())


def retry_delay(attempt, retry_after=None, *, now=None):
    """Return a bounded delay; invalid server hints use local backoff."""
    if retry_after is not None:
        seconds = _valid_delay(retry_after)
        if seconds is not None:
            return seconds
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is not None:
            seconds = _http_date_delay(retry_after, current)
            if seconds is not None:
                return seconds

    try:
        normalized_attempt = max(0, int(attempt))
    except (TypeError, ValueError, OverflowError):
        normalized_attempt = 0
    return min(BASE_DELAY_SECONDS * (2 ** min(normalized_attempt, 30)), MAX_DELAY_SECONDS)
