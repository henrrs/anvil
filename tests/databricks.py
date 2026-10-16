#!/usr/bin/env python3
"""Deterministic offline tests for the Databricks capability."""

from __future__ import annotations

import importlib.util
import io
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_BIN = ROOT / "tests" / "fixtures" / "bin"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dbx = load_module("anvil_databricks_test", ROOT / "scripts" / "databricks.py")
finops = load_module("anvil_finops_test", ROOT / "scripts" / "databricks_finops.py")
dbx.POLL_INTERVAL = 0


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def save_pref(config_home: Path, profile: str = "sample-profile", host: str = "https://workspace-a.example.invalid") -> None:
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config_home)}, clear=False):
        dbx.save_preferences(profile, host)


class TTYInput:
    def __init__(self, value: str):
        self.value = value

    def isatty(self) -> bool:
        return True

    def readline(self, *_args) -> str:
        value, self.value = self.value, ""
        return value


def test_profile_persistence(temp: Path) -> None:
    config_home = temp / "config"
    state = temp / "state.json"
    env = {
        "XDG_CONFIG_HOME": str(config_home),
        "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
        "ANVIL_DATABRICKS_SCENARIO": "valid",
        "ANVIL_DATABRICKS_FIXTURE_STATE": str(state),
    }
    with mock.patch.dict(os.environ, env, clear=False):
        result = dbx.setup()
        prefs_path = Path(result["preferences_path"])
        prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
        check(prefs["selected_profile"] == "sample-profile", "single valid profile was not selected")
        check(prefs["workspace_host"] == "https://workspace-a.example.invalid", "workspace host was not recorded")
        check(prefs_path.stat().st_mode & 0o777 == 0o600, "Databricks preferences are not mode 0600")
        check(prefs_path.parent.stat().st_mode & 0o777 == 0o700, "Databricks preferences directory is not mode 0700")
        rendered = prefs_path.read_text(encoding="utf-8").casefold()
        check(not any(key in rendered for key in ("token", "password", "secret", "credential")), "credential material appeared in preferences")
        prefs_path.write_text(json.dumps({"auth": {"token": ""}}), encoding="utf-8")
        try:
            dbx.load_preferences()
        except dbx.DatabricksError as exc:
            check(exc.category == "PREFERENCES_INVALID", "nested credential field was not rejected")
        else:
            raise AssertionError("nested credential field was accepted in Anvil preferences")
        dbx.save_preferences("sample-profile", "https://workspace-a.example.invalid")
        # Resolve again in a new call to show that future sessions reuse the
        # selected profile without selecting another workspace.
        name, host, _ = dbx.resolve_profile()
        check((name, host) == ("sample-profile", "https://workspace-a.example.invalid"), "selected profile did not persist across calls")


def test_multiple_profile_selection(temp: Path) -> None:
    state = temp / "multiple-state.json"
    env = {
        "XDG_CONFIG_HOME": str(temp / "multiple-config"),
        "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
        "ANVIL_DATABRICKS_SCENARIO": "multiple_profiles",
        "ANVIL_DATABRICKS_FIXTURE_STATE": str(state),
    }
    with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(dbx.sys, "stdin", TTYInput("")), \
            mock.patch("builtins.input", return_value="2"), contextlib.redirect_stdout(io.StringIO()):
        result = dbx.setup()
        check(result["selected_profile"] == "sample-profile-b", "interactive profile choice was ignored")
        check(result["workspace_host"] == "https://workspace-b.example.invalid", "chosen profile host was mismatched")

    with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(dbx.sys, "stdin", io.StringIO("")):
        dbx.load_preferences()
        try:
            dbx.choose_profile(dbx.discover_profiles(), None)
        except dbx.DatabricksError as exc:
            check(exc.category == "PROFILE_SELECTION_REQUIRED", "multiple profiles had the wrong noninteractive error")
        else:
            raise AssertionError("multiple profiles were silently selected in noninteractive setup")


def test_invalid_selected_profile_never_switches(temp: Path) -> None:
    config_home = temp / "invalid-config"
    config_home.mkdir()
    save_pref(config_home)
    env = {
        "XDG_CONFIG_HOME": str(config_home),
        "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
        "ANVIL_DATABRICKS_SCENARIO": "invalid_profile",
        "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "invalid-state.json"),
    }
    with mock.patch.dict(os.environ, env, clear=False):
        try:
            dbx.resolve_profile()
        except dbx.DatabricksError as exc:
            check(exc.category == "PROFILE_INVALID", "invalid selected profile had the wrong error")
        else:
            raise AssertionError("invalid selected profile silently switched to another profile")


def test_cli_minimum_and_missing(temp: Path) -> None:
    env = {
        "XDG_CONFIG_HOME": str(temp / "cli-config"),
        "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
        "ANVIL_DATABRICKS_CLI_VERSION": "0.205.0",
        "ANVIL_DATABRICKS_SCENARIO": "valid",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        value = dbx.status()
        check(value["cli_installed"] and not value["cli_supported"], "outdated CLI was accepted")
    with mock.patch.dict(os.environ, {**env, "ANVIL_DATABRICKS_CLI": "/nonexistent/databricks"}, clear=False):
        value = dbx.status()
        check(not value["cli_installed"] and value["limitation"] == "Databricks CLI is not installed", "missing optional CLI status is unclear")


def test_resource_discovery_and_mutation_safety(temp: Path) -> None:
    config_home = temp / "resources-config"
    config_home.mkdir()
    save_pref(config_home)
    base = {
        "XDG_CONFIG_HOME": str(config_home),
        "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
        "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "resource-state.json"),
        "ANVIL_DATABRICKS_CALL_LOG": str(temp / "resource-calls.jsonl"),
    }
    with mock.patch.dict(os.environ, {**base, "ANVIL_DATABRICKS_SCENARIO": "multiple_clusters"}, clear=False):
        clusters = dbx.discover_clusters()
        check(len(clusters["running"]) == 2 and clusters["selection_required"], "multiple clusters did not require user choice")
    with mock.patch.dict(os.environ, {**base, "ANVIL_DATABRICKS_SCENARIO": "stopped_cluster"}, clear=False):
        clusters = dbx.discover_clusters()
        check(not clusters["running"] and clusters["approval_required_to_start"], "stopped cluster did not require approval")
        try:
            dbx.execute_python("print('hello')", "cluster-stopped")
        except dbx.DatabricksError as exc:
            check(exc.category == "CLUSTER_STOPPED", "stopped Python cluster returned the wrong error")
        else:
            raise AssertionError("stopped cluster was accepted for Python execution")
    with mock.patch.dict(os.environ, {**base, "ANVIL_DATABRICKS_SCENARIO": "multiple_warehouses"}, clear=False):
        warehouses = dbx.discover_warehouses()
        check(len(warehouses["running"]) == 2 and warehouses["selection_required"], "multiple warehouses did not require user choice")
    with mock.patch.dict(os.environ, {**base, "ANVIL_DATABRICKS_SCENARIO": "stopped_warehouse"}, clear=False):
        warehouses = dbx.discover_warehouses()
        check(not warehouses["running"] and warehouses["approval_required_to_start"], "stopped warehouse did not require approval")
        try:
            dbx.execute_sql("SELECT 1", "warehouse-stopped")
        except dbx.DatabricksError as exc:
            check(exc.category == "WAREHOUSE_STOPPED", "stopped warehouse returned the wrong error")
        else:
            raise AssertionError("stopped warehouse was accepted for SQL execution")
    call_path = Path(base["ANVIL_DATABRICKS_CALL_LOG"])
    calls = call_path.read_text(encoding="utf-8") if call_path.exists() else ""
    check("/start" not in calls and "/edit" not in calls and "/resize" not in calls, "resource discovery attempted a mutation")


def test_python_execution_and_cleanup(temp: Path) -> None:
    config_home = temp / "python-config"
    config_home.mkdir()
    save_pref(config_home)
    call_log = temp / "python-calls.jsonl"
    env = {
        "XDG_CONFIG_HOME": str(config_home),
        "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
        "ANVIL_DATABRICKS_SCENARIO": "valid",
        "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "python-state.json"),
        "ANVIL_DATABRICKS_CALL_LOG": str(call_log),
    }
    with mock.patch.dict(os.environ, env, clear=False):
        result = dbx.execute_python("print('safe fixture')", "cluster-a")
        check(result["state"] == "Finished", "Python command did not complete")
        check(result["data"] == "sample result", "Python command output was not parsed")
    calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
    endpoints = [item["endpoint"] for item in calls]
    check("/api/1.2/contexts/create" in endpoints and "/api/1.2/commands/execute" in endpoints, "Python command lifecycle did not create and execute")
    check("/api/1.2/contexts/destroy" in endpoints, "Python execution context was not destroyed")
    check("safe fixture" not in call_log.read_text(encoding="utf-8"), "Python source was written to adapter logs")

    fail_env = {**env, "ANVIL_DATABRICKS_SCENARIO": "command_failure", "ANVIL_DATABRICKS_CALL_LOG": str(temp / "python-fail-calls.jsonl")}
    with mock.patch.dict(os.environ, fail_env, clear=False):
        try:
            dbx.execute_python("raise RuntimeError()", "cluster-a")
        except dbx.DatabricksError as exc:
            check(exc.category == "COMMAND_ERROR", "Python failure was not classified")
        else:
            raise AssertionError("failed Python command was reported as successful")
    failed_calls = Path(fail_env["ANVIL_DATABRICKS_CALL_LOG"]).read_text(encoding="utf-8")
    check("/api/1.2/contexts/destroy" in failed_calls, "failed Python command left its context undisposed")


def test_timeout_cancellation(temp: Path) -> None:
    config_home = temp / "timeout-config"
    config_home.mkdir()
    save_pref(config_home)
    common = {
        "XDG_CONFIG_HOME": str(config_home),
        "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
        "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "timeout-state.json"),
    }
    log = temp / "timeout-python.jsonl"
    with mock.patch.dict(os.environ, {**common, "ANVIL_DATABRICKS_SCENARIO": "command_timeout", "ANVIL_DATABRICKS_CALL_LOG": str(log)}, clear=False), \
            mock.patch.object(dbx, "time", type("Timer", (), {"monotonic": staticmethod(iter([100, 106]).__next__), "sleep": staticmethod(lambda _value: None)})()):
        try:
            dbx.execute_python("pass", "cluster-a", timeout=5)
        except dbx.DatabricksError as exc:
            check(exc.category == "COMMAND_TIMEOUT", "Python timeout was not classified")
        else:
            raise AssertionError("Python timeout was reported as successful")
    python_calls = Path(log).read_text(encoding="utf-8")
    check("/api/1.2/commands/cancel" in python_calls and "/api/1.2/contexts/destroy" in python_calls, "Python timeout did not cancel and clean up")

    log = temp / "timeout-sql.jsonl"
    with mock.patch.dict(os.environ, {**common, "ANVIL_DATABRICKS_SCENARIO": "sql_timeout", "ANVIL_DATABRICKS_CALL_LOG": str(log)}, clear=False), \
            mock.patch.object(dbx, "time", type("Timer", (), {"monotonic": staticmethod(iter([100, 106]).__next__), "sleep": staticmethod(lambda _value: None)})()):
        try:
            dbx.execute_sql("SELECT 1", "warehouse-a", timeout=5)
        except dbx.DatabricksError as exc:
            check(exc.category == "STATEMENT_TIMEOUT", "SQL timeout was not classified")
        else:
            raise AssertionError("SQL timeout was reported as successful")
    sql_calls = Path(log).read_text(encoding="utf-8")
    check("/api/2.0/sql/statements/statement-sample/cancel" in sql_calls, "SQL timeout did not request cancellation")


def test_sql_execution_bounds_and_errors(temp: Path) -> None:
    config_home = temp / "sql-config"
    config_home.mkdir()
    save_pref(config_home)
    common = {
        "XDG_CONFIG_HOME": str(config_home),
        "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
        "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "sql-state.json"),
    }
    log = temp / "sql-calls.jsonl"
    with mock.patch.dict(os.environ, {**common, "ANVIL_DATABRICKS_SCENARIO": "valid", "ANVIL_DATABRICKS_CALL_LOG": str(log)}, clear=False):
        result = dbx.execute_sql("SELECT :value", "warehouse-a", parameters=[{"name": "value", "value": "safe"}])
        check(result["state"] == "SUCCEEDED", "Statement Execution did not complete")
        check("schema_name" in result["columns"] and result["rows"][1][0] == "billing", "SQL response shape was not parsed")
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        submit = next(item for item in calls if item["endpoint"] == "/api/2.0/sql/statements")
        check(submit["row_limit"] == 100 and submit["byte_limit"] == 1_000_000 and submit["disposition"] == "INLINE", "SQL result bounds were not set")
        check("SELECT :value" not in log.read_text(encoding="utf-8"), "SQL text was written to adapter logs")

    mutation_log = temp / "sql-mutation-calls.jsonl"
    with mock.patch.dict(os.environ, {**common, "ANVIL_DATABRICKS_SCENARIO": "valid", "ANVIL_DATABRICKS_CALL_LOG": str(mutation_log)}, clear=False):
        check(not dbx.sql_may_mutate("SELECT 'DROP TABLE x' AS example -- DELETE FROM y\n"), "SQL mutation scanner rejected a read-only literal/comment")
        check(dbx.sql_may_mutate("EXECUTE IMMEDIATE 'DROP TABLE target'"), "dynamic SQL execution was not guarded")
        try:
            dbx.execute_sql("DROP TABLE system.billing.usage", "warehouse-a")
        except dbx.DatabricksError as exc:
            check(exc.category == "SQL_MUTATION_APPROVAL_REQUIRED", "SQL mutation guard returned the wrong error")
        else:
            raise AssertionError("mutating SQL was submitted without approval")
    mutation_calls = mutation_log.read_text(encoding="utf-8") if mutation_log.exists() else ""
    check("/api/2.0/sql/statements" not in mutation_calls, "mutating SQL reached Statement Execution before approval")

    error_env = {**common, "ANVIL_DATABRICKS_SCENARIO": "sql_failure", "ANVIL_DATABRICKS_CALL_LOG": str(temp / "sql-fail.jsonl")}
    with mock.patch.dict(os.environ, error_env, clear=False):
        try:
            dbx.execute_sql("SELECT 1", "warehouse-a")
        except dbx.DatabricksError as exc:
            check(exc.category == "STATEMENT_FAILED", "failed statement was not reported")
        else:
            raise AssertionError("failed statement was reported as successful")

    permission_env = {**common, "ANVIL_DATABRICKS_SCENARIO": "permission_denied", "ANVIL_DATABRICKS_CALL_LOG": str(temp / "sql-permission.jsonl")}
    with mock.patch.dict(os.environ, permission_env, clear=False):
        try:
            dbx.execute_sql("SELECT 1", "warehouse-a")
        except dbx.DatabricksError as exc:
            check(exc.category == "CLI_REQUEST_FAILED", "permission failure was not categorized")
            check("workspace-a" not in str(exc), "permission error leaked remote details")
        else:
            raise AssertionError("permission failure was reported as successful")


def test_system_catalog_discovery(temp: Path) -> None:
    config_home = temp / "catalog-config"
    config_home.mkdir()
    save_pref(config_home)
    env = {
        "XDG_CONFIG_HOME": str(config_home),
        "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
        "ANVIL_DATABRICKS_SCENARIO": "valid",
        "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "catalog-state.json"),
        "ANVIL_DATABRICKS_CALL_LOG": str(temp / "catalog-calls.jsonl"),
    }
    with mock.patch.dict(os.environ, env, clear=False):
        state = dbx.status()
        check(state["profile_valid"] is True and state["identity_reachable"] is True, "doctor status did not validate the selected identity")
        check(state["system_catalog_reachable"] is True, "system catalog was not checked through the running warehouse")
        check(state["system_schemas"] == ["access", "billing", "compute", "lakeflow", "query"], "available system schemas were not reported")
        check(not state["unavailable_system_schemas"], "available key schemas were incorrectly marked unavailable")
        check(state["running_all_purpose_compute"] == 1 and state["running_sql_warehouses"] == 1, "resource counts were not reported")
        tables = dbx.execute_sql("SHOW TABLES IN system.billing", "warehouse-a")
        check({row[1] for row in tables["rows"]} == {"usage", "list_prices"}, "live system-table fixture was not returned")
    calls = Path(env["ANVIL_DATABRICKS_CALL_LOG"]).read_text(encoding="utf-8")
    check("SHOW TABLES" not in calls and "SHOW SCHEMAS" not in calls, "system-table SQL was logged")

    denied_env = {**env, "ANVIL_DATABRICKS_SCENARIO": "permission_denied", "ANVIL_DATABRICKS_FIXTURE_STATE": str(Path(env["ANVIL_DATABRICKS_FIXTURE_STATE"]).with_name("catalog-denied-state.json"))}
    with mock.patch.dict(os.environ, denied_env, clear=False):
        denied = dbx.status()
        check(denied["profile_valid"] is True and denied["identity_reachable"] is True, "system-table permission failure invalidated a valid profile")
        check(denied["system_catalog_reachable"] is False, "system-table permission failure was not reported as unavailable")


def test_finops_scenarios() -> None:
    fixtures = ROOT / "tests" / "fixtures" / "databricks" / "finops"

    def analyze(name: str):
        return finops.analyze(json.loads((fixtures / name).read_text(encoding="utf-8")))

    strong = analyze("strong-underutilization.json")
    check(strong["finding"] == "right_sizing_recommendation", "strong evidence did not yield a conservative recommendation")
    check(strong["evidence_confidence"]["label"] == "HIGH", "strong evidence did not receive high confidence")
    check("probability" in strong["evidence_confidence"]["interpretation"], "confidence score interpretation is missing")

    peaks = analyze("low-average-high-peaks.json")
    check(peaks["finding"] == "no_aggressive_downsize", "high peaks did not block aggressive downsizing")

    shared = analyze("shared-compute.json")
    check(any("approximate" in item for item in shared["coverage_limitations"]), "shared cost attribution was not called approximate")
    check(shared["evidence_confidence"]["score"] < strong["evidence_confidence"]["score"], "shared cost attribution did not reduce confidence")

    incomplete = analyze("incomplete-telemetry.json")
    check(any("coverage" in item.casefold() for item in incomplete["coverage_limitations"]), "incomplete telemetry did not produce a warning")
    check(incomplete["evidence_confidence"]["label"] != "HIGH", "incomplete telemetry received high confidence")

    warehouse = analyze("warehouse.json")
    check(warehouse["finding"] == "warehouse_analysis", "warehouse analysis did not use its own finding path")
    check("cpu_p95_pct" not in warehouse["observed_metrics"], "classic node metrics were treated as warehouse evidence")
    source_text = " ".join(warehouse["sources_used"])
    check("warehouse_events" in source_text and "query.history" in source_text, "warehouse analysis did not retain warehouse/query evidence")

    denied = analyze("no-system-tables.json")
    check(denied["finding"] == "insufficient_evidence" and not denied["optimization_candidates"], "missing system-table access produced a fabricated recommendation")


def test_query_recipes() -> None:
    root = ROOT / "config" / "skills" / "anvil-databricks" / "queries"
    paths = sorted(root.glob("*.sql"))
    check(len(paths) == 7, "expected seven versioned Databricks query recipes")
    write_tokens = re.compile(r"\b(?:INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|OPTIMIZE|VACUUM)\b", re.I)
    for path in paths:
        sql = path.read_text(encoding="utf-8")
        without_comments = re.sub(r"--[^\r\n]*|/\*.*?\*/", " ", sql, flags=re.S)
        check(not re.search(r"\bSELECT\s+\*", without_comments, re.I), f"unbounded SELECT star in {path.name}")
        check(":start_time" in sql and ":end_time" in sql, f"time window parameters missing from {path.name}")
        check("LIMIT " in sql.upper() or "GROUP BY" in sql.upper(), f"recipe is not bounded or aggregated: {path.name}")
        check(not write_tokens.search(without_comments), f"mutation token found in recipe {path.name}")
    job_cost = (root / "job-cost.sql").read_text(encoding="utf-8")
    for join in ("u.workspace_id = r.workspace_id", "u.job_id = r.job_id", "u.run_id = r.run_id", "p.price_start_time <= u.usage_start_time"):
        check(join in job_cost, f"job cost identity/effective price join missing: {join}")
    warehouse_cost = (root / "warehouse-cost.sql").read_text(encoding="utf-8")
    check("p.price_start_time <= u.usage_start_time" in warehouse_cost, "warehouse list-price join does not use the effective usage time")


def test_repository_harness_and_legacy_scan() -> None:
    # Construct the organization identifier so the test source itself never
    # reintroduces the token it is meant to detect.
    legacy = chr(88) + chr(80)
    token = re.compile(r"\b" + re.escape(legacy) + r"\b", re.I)
    listed = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT,
        check=True, capture_output=True,
    ).stdout.split(bytes([0]))
    for raw in listed:
        if not raw:
            continue
        path = ROOT / os.fsdecode(raw)
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if bytes([0]) in data:
            continue
        if token.search(data.decode("utf-8", errors="replace")):
            raise AssertionError(f"legacy organization identifier found in {path.relative_to(ROOT)}")

    agents = (ROOT / "config" / "AGENTS.md").read_text(encoding="utf-8")
    agents_size = (ROOT / "config" / "AGENTS.md").stat().st_size
    check(agents_size <= 4200, "AGENTS.md exceeds its 4,200-byte budget")
    for invariant in (
        "Do not claim success when meaningful validation failed",
        "Never start, stop, restart, resize, edit, or delete Databricks compute",
        "Do not write durable Anvil memory",
        "Do not call it a measured total cloud bill",
    ):
        check(invariant.casefold() in agents.casefold(), f"harness invariant is missing: {invariant}")
    check(not re.search(r"system\.(?:billing|compute|lakeflow|query)\.[a-z_]+", agents), "vendor schema details were embedded in AGENTS.md")

    for skill_path in sorted((ROOT / "config" / "skills").glob("*/SKILL.md")):
        text = skill_path.read_text(encoding="utf-8")
        description = re.search(r"(?m)^description:\s*(.+)$", text)
        check(description is not None, f"skill description missing: {skill_path.parent.name}")
        desc = description.group(1).casefold()
        check("use" in desc or "when" in desc, f"skill does not explain when to use it: {skill_path.parent.name}")
        check("do not use" in desc, f"skill does not explain when not to use it: {skill_path.parent.name}")

    config = json.loads((ROOT / "config" / "opencode.jsonc").read_text(encoding="utf-8"))
    check("model" not in config and "small_model" not in config, "default OpenCode profile pins a model")
    check(set(config["agents"]) == {"anvil", "build", "plan", "general", "explore"}, "unexpected agent set changed")
    check(config.get("mcp", {}).get("servers") == {}, "default config made MCP mandatory")
    adapter = (ROOT / "scripts" / "databricks.py").read_text(encoding="utf-8")
    check("databricks" in adapter.casefold() and "runtime.py" not in adapter and "opencode" not in adapter.casefold(), "Databricks adapter depends on OpenCode runtime internals")
    check("mcp" not in adapter.casefold(), "Databricks adapter has an MCP dependency")
    check("--sensitive" not in adapter and "auth token" not in adapter.casefold() and "auth env" not in adapter.casefold(), "Databricks adapter requests sensitive credential output")

    release = (ROOT / "docs" / "versions" / "v2.2.md").read_text(encoding="utf-8")
    check("| Anvil 2.1 `AGENTS.md` | 4,790 | 1,198 | Baseline |" in release, "old harness size is missing from the release report")
    check(f"| Anvil 2.2 `AGENTS.md` | {agents_size:,} | {round(agents_size / 4):,} |" in release, "current harness size/token estimate does not match the release report")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="anvil-databricks-tests-") as directory:
        temp = Path(directory)
        test_profile_persistence(temp)
        test_multiple_profile_selection(temp)
        test_invalid_selected_profile_never_switches(temp)
        test_cli_minimum_and_missing(temp)
        test_resource_discovery_and_mutation_safety(temp)
        test_python_execution_and_cleanup(temp)
        test_timeout_cancellation(temp)
        test_sql_execution_bounds_and_errors(temp)
        test_system_catalog_discovery(temp)
    test_finops_scenarios()
    test_query_recipes()
    test_repository_harness_and_legacy_scan()
    print("PASS Databricks profile, execution, offline FinOps, query recipe, harness, and legacy-token checks")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL Databricks offline checks: {exc}", file=sys.stderr)
        raise SystemExit(1)
