import unittest
from datetime import datetime, timezone
from email.utils import format_datetime

from retry_policy import retry_delay
from worker import schedule_retry


class RetryPolicyPublicTests(unittest.TestCase):
    def test_zero_is_a_valid_retry_after(self):
        self.assertEqual(retry_delay(4, "0"), 0)

    def test_backoff_is_capped(self):
        self.assertEqual([retry_delay(i) for i in range(7)], [1, 2, 4, 8, 16, 30, 30])

    def test_non_retryable_status_does_not_schedule(self):
        sleeps = []
        response = type("Response", (), {"status_code": 404, "headers": {"Retry-After": "1"}})()
        self.assertFalse(schedule_retry(response, 0, sleeps.append))
        self.assertEqual(sleeps, [])

    def test_http_date_uses_fixed_clock(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        hint = format_datetime(now.replace(second=5), usegmt=True)
        self.assertEqual(retry_delay(0, hint, now=now), 5)


if __name__ == "__main__":
    unittest.main()
