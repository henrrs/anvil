# Repair retry policy without changing its public behavior

The fixture is an existing small HTTP worker. It currently mishandles valid
`Retry-After: 0`, negative/non-finite values, and HTTP-date values. Repair the
root cause and keep policy calculation separate from scheduling.

## Required behavior

- Use `Retry-After` delta-seconds or a valid future HTTP date when supplied.
- Treat zero as a valid immediate retry delay. Clamp valid delays to 30 seconds.
- Invalid, negative, non-finite, or past hints fall back to capped exponential
  backoff: attempt 0 is 1 second, then 2, 4, 8, 16, and 30 seconds.
- Accept HTTP header names without case sensitivity.
- Schedule retries only for 429, 500, 502, 503, and 504. Other statuses must
  not sleep or retry.
- Keep the policy pure and let the worker own the single sleep/scheduling action.
- Use only the Python standard library and preserve the existing function
  interfaces used by the fixture.

## Acceptance

Run `python3 acceptance.py all`. The assertions are independent of the
implementation and use a fixed clock for HTTP-date cases.
