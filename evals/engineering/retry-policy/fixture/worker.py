"""HTTP retry scheduling for a single request worker."""

from retry_policy import retry_delay

RETRIABLE_STATUSES = {429, 500, 502, 503, 504}


def schedule_retry(response, attempt, sleep):
    if response.status_code not in RETRIABLE_STATUSES:
        return False
    delay = retry_delay(attempt, response.headers.get("Retry-After"))
    sleep(delay)
    return True
