#!/usr/bin/env python3
"""A missing first-install profile is normal; malformed input remains visible."""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import configure  # noqa: E402


with tempfile.TemporaryDirectory() as name:
    root = Path(name)
    warnings = io.StringIO()
    with contextlib.redirect_stderr(warnings):
        assert configure._read_config(root / "not-created.jsonc") == {}
    assert warnings.getvalue() == "", "a missing first-install profile should not warn"

    malformed = root / "malformed.jsonc"
    malformed.write_text("{broken", encoding="utf-8")
    with contextlib.redirect_stderr(warnings):
        assert configure._read_config(malformed) == {}
    assert "Could not read prior provider configuration" in warnings.getvalue()

    broken_link = root / "broken-link.jsonc"
    broken_link.symlink_to(root / "missing-target")
    with contextlib.redirect_stderr(warnings):
        assert configure._read_config(broken_link) == {}
    assert "broken symbolic link" in warnings.getvalue()

print("PASS first-install config absence is quiet while malformed and broken-link input remains diagnosable")
