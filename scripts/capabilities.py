#!/usr/bin/env python3
"""Combine runtime and optional Databricks capability state."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import runtime  # noqa: E402


def databricks_module():
    path = ROOT / "scripts" / "databricks.py"
    spec = importlib.util.spec_from_file_location("anvil_databricks_adapter", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Databricks capability adapter could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--binary")
    parser.add_argument("--major", type=int)
    args = parser.parse_args()
    adapter = databricks_module()
    runtime_state = runtime.capabilities(args.binary, args.major)
    databricks_state = adapter.local_status()
    databricks_capabilities = adapter.capabilities(databricks_state)
    if args.format == "json":
        print(json.dumps({
            "schema_version": 1,
            "anvil_version": runtime_state["anvil_version"],
            "runtime": runtime_state,
            "databricks": databricks_state,
            "databricks_capabilities": databricks_capabilities,
        }, indent=2))
        return 0

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "runtime.py"), "capabilities", "--format", "text", *(
            ["--binary", args.binary] if args.binary else []
        ), *(["--major", str(args.major)] if args.major is not None else [])],
        check=False,
    )
    if result.returncode:
        return result.returncode
    print()
    print(adapter.status_text(databricks_state, verbose=args.verbose))
    print("Databricks capabilities")
    from databricks_providers.presentation import capabilities_text
    print("\n".join("  " + line if index else line for index, line in
                      enumerate(capabilities_text(databricks_capabilities).splitlines())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
