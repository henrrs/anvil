#!/usr/bin/env python3
"""Run offline Analytics certification and emit reproducible JUnit/JSON evidence."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
import time
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

UNIT_SUITES = [
    ("context_store", "tests.analytics.test_store", "SQLite context, privacy, WAL, migration and search"),
    ("catalog", "tests.analytics.test_catalog", "Shared Databricks capability, cached catalog and lazy hydration"),
    ("query_materialization", "tests.analytics.test_query_materialization", "Read-only routing, coverage, Parquet snapshots and resumable transfer"),
    ("runtime_sessions", "tests.analytics.test_runtime", "OpenCode 1/2 adapters, runtime warmup, canonical and task sessions"),
    ("http_ui", "tests.analytics.test_http_ui", "Loopback BFF, same-origin API, static UI and contextual SSE"),
    ("tools_service", "tests.analytics.test_tools_service", "OpenCode tool bridges, profile, lineage and route comparison"),
]


class EvidenceResult(unittest.TextTestResult):
    cases: list[dict]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []
        self._case_by_id: dict[str, dict] = {}

    def startTest(self, test):
        case = {"id": test.id(), "status": "RUNNING", "message": ""}
        self.cases.append(case)
        self._case_by_id[test.id()] = case
        super().startTest(test)

    def addSuccess(self, test):
        self._case_by_id[test.id()]["status"] = "PASS"
        super().addSuccess(test)

    def addFailure(self, test, err):
        self._case_by_id[test.id()].update(status="FAIL", message=self._exc_info_to_string(err, test)[-4000:])
        super().addFailure(test, err)

    def addError(self, test, err):
        self._case_by_id[test.id()].update(status="ERROR", message=self._exc_info_to_string(err, test)[-4000:])
        super().addError(test, err)

    def addSkip(self, test, reason):
        self._case_by_id[test.id()].update(status="SKIP", message=str(reason)[:1000])
        super().addSkip(test, reason)


def _run_unit_suite(name: str, module_name: str, description: str) -> dict:
    module = importlib.import_module(module_name)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    started = time.monotonic()
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2, resultclass=EvidenceResult).run(suite)
    elapsed = round(time.monotonic() - started, 3)
    return {"id": name, "description": description,
            "status": "PASS" if result.wasSuccessful() else "FAIL",
            "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
            "skipped": len(result.skipped), "duration_seconds": elapsed,
            "cases": result.cases}


def _run_command(name: str, description: str, argv: list[str], *, optional: bool = False) -> dict:
    started = time.monotonic()
    try:
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=300,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        status = "PASS" if result.returncode == 0 else "FAIL"
        output = (result.stdout + result.stderr).strip()[-8000:]
        return {"id": name, "description": description, "status": status,
                "tests": 1, "failures": 0 if result.returncode == 0 else 1, "errors": 0,
                "skipped": 0, "duration_seconds": round(time.monotonic() - started, 3),
                "cases": [{"id": name, "status": status, "message": output}]}
    except FileNotFoundError as exc:
        status = "SKIP" if optional else "FAIL"
        return {"id": name, "description": description, "status": status,
                "tests": 1, "failures": int(not optional), "errors": 0,
                "skipped": int(optional), "duration_seconds": round(time.monotonic() - started, 3),
                "cases": [{"id": name, "status": status, "message": str(exc)}]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"id": name, "description": description, "status": "ERROR",
                "tests": 1, "failures": 0, "errors": 1,
                "skipped": 0, "duration_seconds": round(time.monotonic() - started, 3),
                "cases": [{"id": name, "status": "ERROR", "message": str(exc)[:4000]}]}


def _write_junit(path: Path, suites: list[dict], elapsed: float) -> None:
    total = sum(item["tests"] for item in suites)
    failures = sum(item["failures"] for item in suites)
    errors = sum(item["errors"] for item in suites)
    skipped = sum(item["skipped"] for item in suites)
    root = ET.Element("testsuites", tests=str(total), failures=str(failures), errors=str(errors),
                       skipped=str(skipped), time=f"{elapsed:.3f}")
    for suite in suites:
        node = ET.SubElement(root, "testsuite", name=suite["id"], tests=str(suite["tests"]),
                             failures=str(suite["failures"]), errors=str(suite["errors"]),
                             skipped=str(suite["skipped"]), time=f"{suite['duration_seconds']:.3f}")
        for case in suite["cases"]:
            item = ET.SubElement(node, "testcase", classname=suite["id"],
                                 name=case["id"].split(".")[-1], time="0")
            if case["status"] in {"FAIL", "ERROR"}:
                failure = ET.SubElement(item, "failure" if case["status"] == "FAIL" else "error",
                                        message=case.get("message", "")[:1000])
                failure.text = case.get("message", "")
            elif case["status"] == "SKIP":
                ET.SubElement(item, "skipped", message=case.get("message", ""))
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _markdown_summary(version: str, timestamp: str, suites: list[dict], limitations: list[str]) -> str:
    total = sum(item["tests"] for item in suites)
    passed = sum(item["tests"] - item["failures"] - item["errors"] - item["skipped"] for item in suites)
    failed = sum(item["failures"] + item["errors"] for item in suites)
    lines = [f"# Anvil Analytics certification — {version}", "", f"Run time: {timestamp}", "",
             f"Result: **{'PASS' if failed == 0 else 'FAIL'}** — {passed}/{total} offline checks passed.", "",
             "| Suite | Result | Checks | Time | Coverage |", "|---|---:|---:|---:|---|"]
    for item in suites:
        count = item["tests"] - item["failures"] - item["errors"] - item["skipped"]
        lines.append(f"| {item['id']} | {item['status']} | {count}/{item['tests']} | "
                     f"{item['duration_seconds']:.3f}s | {item['description']} |")
    lines += ["", "## Scope and limits", "",
              "The certification runs local fixtures, fake OpenCode 1/2 HTTP servers, fake Databricks provider responses, "
              "a loopback BFF, and isolated temporary HOME/XDG lifecycle roots. It does not contact a live OpenCode model, "
              "Databricks workspace, Windows browser, or production credential store.", ""]
    lines.extend(f"- {item}" for item in limitations)
    lines += ["", "## Artifacts", "", "- `report.json` — machine-readable suite and test case results.",
              "- `scenarios.json` — scenario group status and evidence mapping.",
              "- `pytest.xml` — JUnit-compatible test report.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "artifacts" / "analytics-certification")
    args = parser.parse_args(argv)
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    output = args.output.expanduser().absolute()
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    suites = []
    for name, module_name, description in UNIT_SUITES:
        try:
            suites.append(_run_unit_suite(name, module_name, description))
        except Exception as exc:
            suites.append({"id": name, "description": description, "status": "ERROR",
                           "tests": 1, "failures": 0, "errors": 1, "skipped": 0,
                           "duration_seconds": 0.0,
                           "cases": [{"id": name, "status": "ERROR", "message": str(exc)[:4000]}]})
    suites.append(_run_command("lifecycle", "Fresh install, 2.15→2.16 upgrade, idempotency, dry-run, rollback and user data preservation",
                               [sys.executable, "tests/analytics_lifecycle.py"]))
    suites.append(_run_command("frontend_syntax", "Static frontend JavaScript syntax", ["node", "--check", "web/analytics/app.js"], optional=True))
    suites.append(_run_command("python_syntax", "Compile Analytics modules", [sys.executable, "-m", "py_compile",
        *[str(path.relative_to(ROOT)) for path in (ROOT / "scripts" / "analytics").glob("*.py")],
        "scripts/analytics_service.py"]))
    elapsed = round(time.monotonic() - started, 3)
    cases = [case for suite in suites for case in suite["cases"]]
    status = "PASS" if all(suite["status"] in {"PASS", "SKIP"} for suite in suites) else "FAIL"
    report = {"schema_version": 1, "anvil_version": version, "status": status,
              "run_at": stamp, "duration_seconds": elapsed,
              "totals": {"tests": sum(item["tests"] for item in suites),
                         "failures": sum(item["failures"] for item in suites),
                         "errors": sum(item["errors"] for item in suites),
                         "skipped": sum(item["skipped"] for item in suites)},
              "suites": suites}
    scenario_groups = [
        {"scenario": item["description"], "suite": item["id"], "status": item["status"],
         "evidence": [case["id"] for case in item["cases"]]} for item in suites]
    limitations = ["Live OpenCode prompt/tool execution and model quality were not measured.",
                   "Live Databricks permissions, authentication, SQL warehouse behavior, and Arrow CloudFetch were not measured.",
                   "Windows-to-WSL browser reachability is environment-specific and remains a host-side check.",
                   "DuckDB and PyArrow availability depends on the user's Python environment; missing optional packages are reported as degraded."]
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "scenarios.json").write_text(json.dumps({"schema_version": 1, "scenarios": scenario_groups,
        "limitations": limitations}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_junit(output / "pytest.xml", suites, elapsed)
    (output / "summary.md").write_text(_markdown_summary(version, stamp, suites, limitations), encoding="utf-8")
    print(f"Analytics certification {status}: {report['totals']['tests']} checks; artifacts {output}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
