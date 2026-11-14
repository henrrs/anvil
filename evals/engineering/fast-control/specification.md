# FAST control — Validate a requested local batch limit

Repair `limit.py` while keeping the `choose_limit(requested=None, default=100,
maximum=10000)` interface. A missing request uses the default. Otherwise accept a
positive integer or a base-10 integer string from 1 through `maximum`, inclusive.
Reject booleans, fractional values, malformed strings, zero, negative values,
values above the maximum, and invalid defaults/maximums with `ValueError`.
Keep this small and local; use only the standard library.

Run `python3 -m unittest discover -s tests` and describe the checks performed.
