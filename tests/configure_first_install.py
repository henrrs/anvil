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

    config = root / "opencode"
    config.mkdir()
    (config / "opencode.json").write_text('{"plugin":["@company/audit"]}', encoding="utf-8")
    template = ROOT / "config/runtimes/opencode-v1.jsonc"
    merged = configure.parse_jsonc(template.read_text(encoding="utf-8"), str(template))
    configure.merge_prior_configuration(merged, config)
    assert merged["plugin"] == ["@company/audit"]

    (config / "opencode.json").write_text("{broken", encoding="utf-8")
    try:
        configure.merge_prior_configuration(
            configure.parse_jsonc(template.read_text(encoding="utf-8"), str(template)), config)
    except ValueError as exc:
        assert "cannot be safely read" in str(exc)
    else:
        raise AssertionError("malformed user plugin config must block the merge")

print("PASS first-install config absence is quiet while malformed and broken-link input remains diagnosable")
