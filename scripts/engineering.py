#!/usr/bin/env python3
"""Anvil's optional engineering execution core; use --help for explicit operations."""

from engineering.cli import main
from public_errors import run_public


if __name__ == "__main__":
    raise SystemExit(run_public(main, command="Anvil Engineering"))
