from ingestion import retry_delay


def test_retry_delay_uses_bounded_exponential_backoff():
    assert retry_delay(20) <= 30.0
