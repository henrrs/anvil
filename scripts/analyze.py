#!/usr/bin/env python3
"""Local, bounded Anvil intent and analytical intelligence helper."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from analysis.adapter import artifact_components  # noqa: E402
from analysis.contracts import validate_analysis_plan, validate_task_brief  # noqa: E402
from analysis.errors import AnalysisError  # noqa: E402
from analysis.findings import validate_result  # noqa: E402
from analysis.primitives import execute_plan  # noqa: E402
from analysis.profiling import MAX_ROWS, profile_file  # noqa: E402
from communication.errors import CommunicationError  # noqa: E402


def _json_file(raw: str) -> Any:
    path = Path(os.path.abspath(Path(raw).expanduser()))
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise AnalysisError("INPUT_UNSAFE", "Contract input path contains a symbolic link; links are not followed.")
    if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
        raise AnalysisError("INPUT_LIMIT_EXCEEDED", "Contract input must be an explicitly named regular JSON file no larger than 5 MiB.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise AnalysisError("INPUT_UNREADABLE", "Could not read valid UTF-8 JSON from the named contract file.") from None


def _emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    profile = sub.add_parser("profile", help="deterministically profile a named CSV, TSV, JSON, or JSON Lines table")
    profile.add_argument("input")
    profile.add_argument("--max-rows", type=int, default=MAX_ROWS)
    execute = sub.add_parser("execute", help="validate and run a bounded deterministic analysis plan")
    execute.add_argument("input")
    execute.add_argument("plan")
    for name in ("validate-brief", "validate-plan", "validate-result", "artifact-components"):
        command = sub.add_parser(name, help=f"validate or adapt a structured {name.removeprefix('validate-')} contract")
        command.add_argument("json_file")
    args = parser.parse_args(argv)
    try:
        if args.command == "profile":
            value = profile_file(args.input, max_rows=args.max_rows)
        elif args.command == "execute":
            value = execute_plan(args.input, _json_file(args.plan))
        elif args.command == "validate-brief":
            value = validate_task_brief(_json_file(args.json_file))
        elif args.command == "validate-plan":
            value = validate_analysis_plan(_json_file(args.json_file))
        elif args.command == "validate-result":
            value = validate_result(_json_file(args.json_file))
        else:
            value = artifact_components(_json_file(args.json_file))
        _emit(value)
        return 0
    except AnalysisError as exc:
        print(f"ERROR {exc.code}: {exc}", file=sys.stderr)
        if exc.remediation:
            print(f"Next step: {exc.remediation}", file=sys.stderr)
        return 1
    except CommunicationError as exc:
        print(f"ERROR {exc.code}: {exc}", file=sys.stderr)
        if exc.remediation:
            print(f"Next step: {exc.remediation}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
