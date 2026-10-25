#!/usr/bin/env python3
"""Anvil Communication & Artifact Intelligence local CLI."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from communication.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
