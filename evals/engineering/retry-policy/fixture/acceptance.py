"""Independent behavior checks for the existing HTTP worker fixture."""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

from retry_policy import retry_delay
from worker import schedule_retry


def policy():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert retry_delay(0) == 1
    assert retry_delay(1) == 2
    assert retry_delay(3) == 8
    assert retry_delay(100) == 30
    assert retry_delay(2, "0") == 0
    assert retry_delay(1, "4.5") == 4.5
    assert retry_delay(1, "900") == 30
    future = format_datetime(now + timedelta(seconds=12), usegmt=True)
    assert retry_delay(2, future, now=now) == 12
    past = format_datetime(now - timedelta(seconds=1), usegmt=True)
    assert retry_delay(2, past, now=now) == 4
    for hint in (None, "", "bad", "-1", "nan", "inf"):
        assert retry_delay(2, hint, now=now) == 4


def worker():
    calls = []
    response = SimpleNamespace(status_code=429, headers={"rEtRy-AfTeR": "0"})
    assert schedule_retry(response, 0, calls.append) is True
    assert calls == [0]
    calls.clear()
    response.status_code = 404
    assert schedule_retry(response, 1, calls.append) is False
    assert calls == []


def all_checks():
    policy()
    worker()


if __name__ == "__main__":
    import sys
    cases = {"policy": policy, "worker": worker, "all": all_checks}
    cases[sys.argv[1]]()
    print("PASS retry policy acceptance", sys.argv[1])
