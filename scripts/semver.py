"""Strict helpers for comparing Anvil's numeric semantic release versions."""

from __future__ import annotations

import re


_RELEASE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


def parse(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = _RELEASE.fullmatch(value.strip())
    return tuple(map(int, match.groups())) if match else None


def compare(left: object, right: object) -> int | None:
    a, b = parse(left), parse(right)
    if a is None or b is None:
        return None
    return (a > b) - (a < b)


def supported_migration(source: object, target: object, *, minor_window: int = 5) -> bool:
    """Return whether an installed release is inside the documented source window."""
    old = parse(source)
    new = parse(target)
    if old is None or new is None or old > new or old[0] != new[0]:
        return False
    minor_distance = new[1] - old[1]
    return 0 <= minor_distance <= minor_window
