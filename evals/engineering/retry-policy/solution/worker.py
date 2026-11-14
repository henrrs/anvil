"""HTTP retry scheduling; this module owns the one sleep operation."""

from retry_policy import retry_delay

RETRIABLE_STATUSES = {429, 500, 502, 503, 504}


def _header(headers, wanted):
    for name, value in headers.items():
        if isinstance(name, str) and name.casefold() == wanted.casefold():
            return value
    return None


def schedule_retry(response, attempt, sleep):
    if response.status_code not in RETRIABLE_STATUSES:
        return False
    delay = retry_delay(attempt, _header(response.headers, "Retry-After"))
    sleep(delay)
    return True
