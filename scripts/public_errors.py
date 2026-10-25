"""Small sanitized exception boundary for user-facing Python commands."""

from __future__ import annotations

import os
import re
import secrets
import sys
import traceback
from collections.abc import Callable


_SECRET_PATTERNS = (
    re.compile(r"(?i)(\b(?:token|password|secret|client_secret|authorization|credential)\b\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|Bearer\s+)[A-Za-z0-9._~+/-]+=*", re.IGNORECASE),
)


def _redact(value: str) -> str:
    for index, pattern in enumerate(_SECRET_PATTERNS):
        replacement = r"\1[redacted]" if index == 0 else "[redacted]"
        value = pattern.sub(replacement, value)
    return value


def run_public(main: Callable[[], int], *, command: str) -> int:
    """Render unexpected command failures without a traceback unless DEBUG=1."""
    try:
        return main()
    except Exception as exc:  # noqa: BLE001 - deliberate outer CLI boundary
        diagnostic_id = secrets.token_hex(4).upper()
        print(f"{command} failed: an unexpected internal error prevented completion.", file=sys.stderr)
        print("Review the affected local state before retrying.", file=sys.stderr)
        print(f"Diagnostic ID  ANVIL-{diagnostic_id}", file=sys.stderr)
        print("Run with DEBUG=1 for technical details.", file=sys.stderr)
        if os.environ.get("DEBUG") == "1":
            print("\nDebug traceback (secret-like values redacted):", file=sys.stderr)
            frames = traceback.extract_tb(exc.__traceback__)
            for frame in frames:
                print(f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}', file=sys.stderr)
                if frame.line:
                    print(f"    {_redact(frame.line)}", file=sys.stderr)
            print(f"{type(exc).__name__}: {_redact(str(exc))}", file=sys.stderr)
        return 1
