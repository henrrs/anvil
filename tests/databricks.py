#!/usr/bin/env python3
"""Deterministic offline tests for the Databricks capability."""

from __future__ import annotations

import importlib.util
import io
import contextlib
import json
import hashlib
import io as byte_io
import os
import re
import stat
import subprocess
import sys
import tempfile
import types
import urllib.error
import zipfile
from typing import Any
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
sdk_worker = load_module("anvil_databricks_sdk_worker_test", ROOT / "scripts" / "databricks_providers" / "sdk_worker.py")
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
        "PATH": "/usr/bin:/bin",
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
        with mock.patch.object(dbx.cli_install, "attempt_cli_install", side_effect=AssertionError("healthy CLI was reinstalled")):
            repeated = dbx.setup()
        check(repeated["selected_profile"] == "sample-profile", "repeat setup changed the selected workspace")


def test_cli_environment_auth_without_named_profile(temp: Path) -> None:
    config_home = temp / "environment-auth-config"
    env = {
        "HOME": str(temp / "environment-auth-home"),
        "XDG_CONFIG_HOME": str(config_home),
        "XDG_DATA_HOME": str(temp / "environment-auth-data"),
        "DATABRICKS_CONFIG_FILE": str(temp / "missing-databrickscfg"),
        "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
        "ANVIL_DATABRICKS_SCENARIO": "environment_auth",
        "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "environment-auth-state.json"),
    }
    original_run = subprocess.run
    commands: list[list[str]] = []

    def recording_run(command, *args, **kwargs):
        if isinstance(command, (list, tuple)) and command and str(command[0]) == str(FIXTURE_BIN / "databricks"):
            commands.append(list(command))
        return original_run(command, *args, **kwargs)

    with mock.patch.dict(os.environ, env, clear=False), \
            mock.patch("subprocess.run", side_effect=recording_run):
        configured = dbx.setup()
        check(configured["selected_profile"] == "__ANVIL_DEFAULT__", "default CLI Unified Authentication was not accepted without a named profile")
        selected, host, profiles = dbx.resolve_profile()
        check(selected == "__ANVIL_DEFAULT__" and host == "https://workspace-a.example.invalid" and profiles == [],
              "saved default CLI authentication did not resolve on a later operation")
    identity_commands = [command for command in commands if command[1:3] in (["auth", "describe"], ["current-user", "me"])]
    check(len(identity_commands) >= 4, "default CLI auth was not revalidated on setup and operation")
    check(all("--profile" not in command for command in identity_commands), "internal default profile sentinel leaked to the CLI")


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


def test_cli_install_failure_survives_unsupported_binary(temp: Path) -> None:
    binary = temp / "unsupported-cli" / "databricks"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\nprintf 'Databricks CLI v0.205.0\\n'\n", encoding="utf-8")
    binary.chmod(0o700)
    env = {"XDG_CONFIG_HOME": str(temp / "unsupported-cli-config"),
           "XDG_DATA_HOME": str(temp / "unsupported-cli-data"),
           "ANVIL_DATABRICKS_CLI": str(binary),
           "DATABRICKS_CONFIG_FILE": str(temp / "unsupported-cli-no-config")}
    with mock.patch.dict(os.environ, env, clear=False):
        dbx.provider_state.save_state({"providers": {"cli": {"status": "BLOCKED", "failure": "policy-blocked",
                                                                  "installed": True, "executable": str(binary)}}})
        value = dbx.status()
        check(value["cli_provider_status"] == "UNSUPPORTED_VERSION", "unsupported CLI status was hidden by a prior setup failure")
        check(value["cli_setup_failure"] == "policy-blocked", "CLI installation failure was lost from doctor state")


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


def test_provider_resolver_and_path_regression(temp: Path) -> None:
    providers = {
        "cli": {"status": "READY"}, "sdk": {"status": "READY"},
        "sql_connector": {"status": "READY"}, "connect": {"status": "READY"},
        "vscode": {"status": "AVAILABLE"},
    }
    selected = dbx.resolver.resolve(providers, auth_valid=True)
    check(selected["sql.execute"]["provider"] == "cli", "CLI was not preferred for SQL")
    check(selected["python.execute"]["provider"] == "cli", "CLI was not preferred for Python")
    check(selected["spark.develop"]["provider"] == "connect", "Connect was not selected for Spark development")
    check(selected["bundles.run"]["provider"] == "cli", "CLI was not selected for Bundles")
    fallback = dbx.resolver.resolve({**providers, "cli": {"status": "BLOCKED"}}, auth_valid=True)
    check(fallback["sql.execute"]["provider"] == "sdk", "SDK did not provide SQL fallback")
    check(fallback["python.execute"]["provider"] == "sdk", "SDK did not provide Python fallback")
    connector = dbx.resolver.resolve({"sql_connector": {"status": "READY"}}, auth_valid=True)
    check(connector["sql.execute"]["provider"] == "sql_connector", "SQL Connector was not a specialized SQL fallback")
    assisted = dbx.resolver.resolve({"vscode": {"status": "AVAILABLE"}}, auth_valid=True)
    check(assisted["python.execute"]["state"] == "ASSISTED" and not assisted["python.execute"]["headless"],
          "VS Code was incorrectly reported as headless execution")
    check(assisted["bundles.run"]["state"] == "ASSISTED", "VS Code Bundles flow was not marked assisted")

    binary = temp / "installed" / "databricks"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\nprintf 'Databricks CLI v1.5.0\\n'\n", encoding="utf-8")
    binary.chmod(0o700)
    env = {"PATH": "/usr/bin:/bin", "ANVIL_DATABRICKS_CLI": "/nonexistent/test-cli"}
    with mock.patch.dict(os.environ, env, clear=False):
        os.environ.pop("ANVIL_DATABRICKS_CLI", None)
        result = dbx.discovery.discover_cli({"providers": {"cli": {"executable": str(binary)}}})
    check(result["status"] == "READY" and result["installed"], "cached absolute CLI path was not reused")
    check(result["executable"] == str(binary.resolve()), "CLI absolute path was not canonicalized")
    check(result["path_visible"] is False, "PATH mismatch was not detected")

    code_dir = temp / "vscode-bin"
    code_dir.mkdir()
    code = code_dir / "code"
    code.write_text("#!/bin/sh\nprintf 'databricks.databricks\\n'\n", encoding="utf-8")
    code.chmod(0o700)
    with mock.patch.dict(os.environ, {"PATH": str(code_dir), "ANVIL_VSCODE_CLI": str(code)}, clear=False):
        dbx.discovery._VSCODE_CACHE = None
        check(dbx.discovery._vscode()["status"] == "AVAILABLE", "official VS Code extension was not detected")
        code.write_text("#!/bin/sh\nprintf 'other.extension\\n'\n", encoding="utf-8")
        dbx.discovery._VSCODE_CACHE = None
        check(dbx.discovery._vscode()["extension"] == "NO", "unrelated VS Code extension was mistaken for Databricks")
    with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin", "ANVIL_VSCODE_CLI": "/nonexistent/code"}, clear=False):
        dbx.discovery._VSCODE_CACHE = None
        check(dbx.discovery._vscode()["available"] is False, "VS Code was reported without its public CLI")


def test_provider_state_dry_run_and_installer(temp: Path) -> None:
    config_home = temp / "state-config"
    env = {"XDG_CONFIG_HOME": str(config_home), "XDG_DATA_HOME": str(temp / "state-data"),
           "HOME": str(temp / "home"), "PATH": "/nonexistent", "ANVIL_DATABRICKS_CLI": "/nonexistent/databricks"}
    with mock.patch.dict(os.environ, env, clear=False):
        legacy_path = dbx.provider_state.state_path()
        legacy_path.parent.mkdir(parents=True)
        legacy_path.write_text(json.dumps({"schema_version": 1, "selected_profile": "engineering",
                                           "workspace_host": "https://workspace-a.example.invalid"}), encoding="utf-8")
        old = dbx.provider_state.load_state()
        check(old["schema_version"] == 2 and old["selected_profile"] == "engineering", "2.2 provider preferences did not migrate")
        dbx.provider_state.save_state(old)
        check(legacy_path.stat().st_mode & 0o777 == 0o600, "provider state file is not private")
        check(legacy_path.parent.stat().st_mode & 0o777 == 0o700, "provider state directory is not private")
        check(not list(legacy_path.parent.glob(".databricks.*")), "atomic provider write left a temporary file")
        try:
            dbx.provider_state.save_state({"providers": {"sdk": {"access_token": "not-stored"}}})
        except ValueError:
            pass
        else:
            raise AssertionError("provider state accepted a credential field")
        dry_state_path = legacy_path
        before = dry_state_path.read_bytes()
        with mock.patch.object(dbx.cli_install, "attempt_cli_install", side_effect=AssertionError("dry run attempted CLI installation")), \
                mock.patch.object(dbx.cli_install, "install_sdk", side_effect=AssertionError("dry run attempted SDK setup")):
            plan = dbx.setup(dry_run=True)
        check(plan["dry_run"] and plan["changes_performed"] is False, "dry-run result did not say no changes")
        check(dry_state_path.read_bytes() == before, "dry-run changed Anvil provider state")
        check(not (Path(env["XDG_DATA_HOME"]) / "anvil").exists(), "dry-run created Anvil provider data")

    release_name = "databricks_cli_1.21.0_linux_amd64.zip"
    archive_data = byte_io.BytesIO()
    with zipfile.ZipFile(archive_data, "w") as package:
        package.writestr("databricks", "#!/bin/sh\nprintf 'Databricks CLI v1.21.0\\n'\n")
    archive = archive_data.getvalue()
    digest = hashlib.sha256(archive).hexdigest()
    release = {"assets": [
        {"name": release_name, "browser_download_url": "https://fixture.invalid/cli.zip"},
        {"name": "databricks_cli_1.21.0_SHA256SUMS", "browser_download_url": "https://fixture.invalid/SHA256SUMS"},
    ]}
    payloads = {dbx.cli_install.RELEASE_API: json.dumps(release).encode(),
                "https://fixture.invalid/cli.zip": archive,
                "https://fixture.invalid/SHA256SUMS": f"{digest}  {release_name}\n".encode()}
    with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(temp / "install-data")}, clear=False), \
            mock.patch.object(dbx.cli_install, "_request", side_effect=lambda url, _limit=0: payloads[url]):
        installed = dbx.cli_install.attempt_cli_install()
    check(installed["status"] == "READY" and installed["version"] == "1.21.0", "verified user-local CLI install failed")
    path = Path(installed["executable"])
    check(path.is_file() and os.access(path, os.X_OK), "installed CLI is not executable")
    check(path.parent.stat().st_mode & 0o777 == 0o700, "Anvil CLI installation directory is not private")

    with mock.patch.object(dbx.cli_install, "_request", side_effect=urllib.error.HTTPError("https://fixture.invalid", 403, "blocked", {}, None)):
        blocked = dbx.cli_install.attempt_cli_install()
    check(blocked["status"] == "BLOCKED" and blocked["failure"] == "policy-blocked", "HTTP 403 was not classified as policy blocked")
    with mock.patch.object(dbx.cli_install, "_request", side_effect=PermissionError()):
        denied = dbx.cli_install.attempt_cli_install()
    check(denied["status"] == "BLOCKED" and denied["failure"] == "permission-denied", "local permission failure was not classified")


def test_sdk_fallback_routes_core_operations(temp: Path) -> None:
    config_home = temp / "sdk-config"
    config_home.mkdir()
    save_pref(config_home)
    config_file = temp / "databrickscfg"
    config_file.write_text("[sample-profile]\nhost = https://workspace-a.example.invalid\n", encoding="utf-8")
    env = {"XDG_CONFIG_HOME": str(config_home), "DATABRICKS_CONFIG_FILE": str(config_file),
           "ANVIL_DATABRICKS_CLI": "/nonexistent/cli"}
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_sdk(operation: str, *, profile: str | None = None, timeout: int = 120, **payload: Any):
        calls.append((operation, payload))
        if operation == "identity":
            return {"identity": {"userName": "sample-user"}, "host": "https://workspace-a.example.invalid"}
        if operation == "clusters.list":
            return {"clusters": [{"cluster_id": "cluster-a", "cluster_name": "Shared", "state": "RUNNING",
                                  "cluster_source": "UI", "num_workers": 2}]}
        if operation == "clusters.get":
            return {"cluster_id": payload["cluster_id"], "state": "RUNNING"}
        if operation == "warehouses.list":
            return {"warehouses": [{"id": "warehouse-a", "name": "Analytics", "state": "RUNNING"}]}
        if operation == "warehouses.get":
            return {"id": payload["warehouse_id"], "state": "RUNNING"}
        if operation == "jobs.list":
            return {"jobs": [{"job_id": 17, "settings": {"name": "daily"}}]}
        if operation == "jobs.get":
            return {"job_id": int(payload["job_id"]), "settings": {"name": "daily"}}
        if operation == "pipelines.list":
            return {"pipelines": [{"pipeline_id": "pipeline-a", "name": "daily"}]}
        if operation == "pipelines.get":
            return {"pipeline_id": payload["pipeline_id"], "name": "daily"}
        if operation == "workspace.list":
            return {"objects": [{"path": payload["path"], "object_type": "DIRECTORY"}]}
        if operation == "python.execute":
            return {"status": "Finished", "results": {"resultType": "text", "data": "executed"}}
        if operation == "sql.execute":
            return {"statement_id": "sdk-statement", "status": {"state": "SUCCEEDED"},
                    "manifest": {"schema": {"columns": [{"name": "value"}]}},
                    "result": {"data_array": [[1]]}}
        raise AssertionError(f"unexpected SDK operation {operation}")

    blocked_cli = {"status": "BLOCKED", "installed": False, "failure": "policy-blocked"}
    ready_sdk = {"status": "READY", "installed": True, "python": sys.executable, "version": "0.141.0", "isolated": True}
    setup_providers = {"cli": blocked_cli, "sdk": ready_sdk,
                       "vscode": {"status": "AVAILABLE", "available": True, "extension": "YES"},
                       "connect": {"status": "NOT_INSTALLED"}, "sql_connector": {"status": "NOT_INSTALLED"}}
    with mock.patch.dict(os.environ, env, clear=False), \
            mock.patch.object(dbx, "cli_provider", return_value=blocked_cli), \
            mock.patch.object(dbx, "sdk_provider", return_value=ready_sdk), \
            mock.patch.object(dbx.sdk, "call", side_effect=fake_sdk):
        with mock.patch.object(dbx, "provider_snapshot", return_value=setup_providers), \
                mock.patch.object(dbx.cli_install, "attempt_cli_install", return_value={"status": "BLOCKED", "failure": "policy-blocked"}) as install, \
                mock.patch.object(dbx.cli_install, "install_sdk", side_effect=AssertionError("existing SDK was reinstalled")):
            configured = dbx.setup()
            check(install.call_count == 1, "setup did not attempt official CLI installation")
            check(configured["overall"] == "READY", "healthy SDK fallback was marked unhealthy")
            check(configured["providers"]["cli"]["status"] == "BLOCKED", "CLI install failure was not observable")
            check(configured["providers"]["sdk"]["status"] == "READY", "existing SDK was lost after CLI install failure")
        clusters = dbx.discover_clusters()
        check(clusters["running"][0]["cluster_id"] == "cluster-a", "SDK compute discovery did not normalize results")
        python_result = dbx.execute_python("print('hello')", "cluster-a")
        check(python_result["data"] == "executed", "SDK Python result was not normalized")
        sql_result = dbx.execute_sql("SELECT 1", "warehouse-a")
        check(sql_result["rows"] == [[1]] and sql_result["columns"] == ["value"], "SDK SQL result was not normalized")
        sdk_operations = {
            "clusters.get": dbx.json_from_cli(["clusters", "get", "cluster-a"], profile="sample-profile"),
            "warehouses.get": dbx.json_from_cli(["warehouses", "get", "warehouse-a"], profile="sample-profile"),
            "jobs.list": dbx.json_from_cli(["jobs", "list"], profile="sample-profile"),
            "jobs.get": dbx.json_from_cli(["jobs", "get", "17"], profile="sample-profile"),
            "pipelines.list": dbx.json_from_cli(["pipelines", "list"], profile="sample-profile"),
            "pipelines.get": dbx.json_from_cli(["pipelines", "get", "pipeline-a"], profile="sample-profile"),
            "workspace.list": dbx.json_from_cli(["workspace", "list", "/Shared"], profile="sample-profile"),
        }
        check(sdk_operations["jobs.get"]["job_id"] == 17 and sdk_operations["pipelines.get"]["pipeline_id"] == "pipeline-a"
              and sdk_operations["workspace.list"]["objects"][0]["path"] == "/Shared",
              "SDK workspace, jobs, pipelines or resource-get operation did not normalize")
        routes = {"compute.list": dbx.active_provider("compute.list"),
                  "jobs.list": dbx.active_provider("jobs.list"),
                  "workspace.list": dbx.active_provider("workspace.list"),
                  "python.execute": dbx.active_provider("python.execute"),
                  "sql.execute": dbx.active_provider("sql.execute")}
        check(set(routes.values()) == {"sdk"}, "core capability resolver did not route to the SDK")
    operations = {operation for operation, _ in calls}
    check({"identity", "clusters.list", "clusters.get", "warehouses.list", "warehouses.get", "jobs.list", "jobs.get",
           "pipelines.list", "pipelines.get", "workspace.list", "python.execute", "sql.execute"} <= operations,
          "CLI-blocked SDK fallback did not cover core operations")


def test_sdk_worker_uses_pinned_official_api_contracts() -> None:
    class Response:
        def __init__(self, data: dict[str, Any]):
            self.data = data
            self.statement_id = data.get("statement_id")

        def as_dict(self):
            return self.data

    class Parameter:
        def __init__(self, **values):
            self.values = values

        def as_dict(self):
            return self.values

    def enum_value(value: str):
        return types.SimpleNamespace(value=value)

    class Waiter:
        response = types.SimpleNamespace(id="command-a")

        def result(self, *, timeout):
            check(timeout.total_seconds() == 30, "SDK Python execution timeout was not bounded and passed")
            return Response({"id": "command-a", "status": "Finished", "results": {"resultType": "text", "data": "ok"}})

    def execute_python(**kwargs):
        calls["python_execute"] = kwargs
        return Waiter()

    calls: dict[str, Any] = {}
    command_api = types.SimpleNamespace(
        create_and_wait=lambda **kwargs: types.SimpleNamespace(id="context-a"),
        execute=execute_python,
        destroy=lambda **kwargs: calls.setdefault("python_destroy", kwargs),
        cancel=lambda **kwargs: calls.setdefault("python_cancel", kwargs),
    )

    class StatementAPI:
        def execute_statement(self, **kwargs):
            calls["sql_execute"] = kwargs
            return Response({"statement_id": "statement-a", "status": {"state": "SUCCEEDED"},
                             "manifest": {"schema": {"columns": [{"name": "value"}]}},
                             "result": {"data_array": [["safe"]]}})

        def get_statement(self, statement_id):
            calls["sql_get"] = statement_id
            return Response({})

        def cancel_execution(self, statement_id):
            calls["sql_cancel"] = statement_id

    def record_call(name: str, value: Any):
        def invoke_method(**kwargs):
            calls[name] = kwargs
            return value
        return invoke_method

    workspace_client = types.SimpleNamespace(
        command_execution=command_api,
        statement_execution=StatementAPI(),
        clusters=types.SimpleNamespace(
            list=lambda: [types.SimpleNamespace(cluster_id="cluster-a", state="RUNNING")],
            get=record_call("clusters_get", types.SimpleNamespace(cluster_id="cluster-a", state="RUNNING"))),
        warehouses=types.SimpleNamespace(
            list=lambda: [types.SimpleNamespace(id="warehouse-a", state="RUNNING")],
            get=record_call("warehouses_get", types.SimpleNamespace(id="warehouse-a", state="RUNNING"))),
        jobs=types.SimpleNamespace(
            list=record_call("jobs_list", [types.SimpleNamespace(job_id=17)]),
            get=record_call("jobs_get", types.SimpleNamespace(job_id=17))),
        pipelines=types.SimpleNamespace(
            list_pipelines=record_call("pipelines_list", [types.SimpleNamespace(pipeline_id="pipeline-a")]),
            get=record_call("pipelines_get", types.SimpleNamespace(pipeline_id="pipeline-a"))),
        workspace=types.SimpleNamespace(
            list=record_call("workspace_list", [types.SimpleNamespace(path="/Shared")]))
    )

    sdk_module = types.ModuleType("databricks.sdk")
    sdk_module.__path__ = []
    sdk_module.WorkspaceClient = lambda **_kwargs: workspace_client
    root_module = types.ModuleType("databricks")
    root_module.__path__ = []
    service_module = types.ModuleType("databricks.sdk.service")
    compute_module = types.ModuleType("databricks.sdk.service.compute")
    compute_module.Language = types.SimpleNamespace(PYTHON=enum_value("PYTHON"))
    sql_module = types.ModuleType("databricks.sdk.service.sql")
    sql_module.StatementParameterListItem = Parameter
    sql_module.ExecuteStatementRequestOnWaitTimeout = types.SimpleNamespace(CONTINUE=enum_value("CONTINUE"))
    sql_module.Disposition = types.SimpleNamespace(INLINE=enum_value("INLINE"))
    sql_module.Format = types.SimpleNamespace(JSON_ARRAY=enum_value("JSON_ARRAY"))
    service_module.compute = compute_module
    service_module.sql = sql_module
    modules = {"databricks": root_module, "databricks.sdk": sdk_module,
               "databricks.sdk.service": service_module,
               "databricks.sdk.service.compute": compute_module,
               "databricks.sdk.service.sql": sql_module}

    def invoke(request: dict[str, Any]) -> dict[str, Any]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.dict(sys.modules, modules), mock.patch("sys.stdin", io.StringIO(json.dumps(request))), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = sdk_worker.main()
            check(code == 0, f"SDK worker returned a failure for {request['operation']}: {stderr.getvalue()}")
        return json.loads(stdout.getvalue())

    python = invoke({"operation": "python.execute", "timeout": 30,
                     "payload": {"cluster_id": "cluster-a", "code": "print('ok')"}})
    check(python["status"] == "Finished" and python["results"]["data"] == "ok", "SDK Command Execution response was not returned")
    check(calls["python_execute"]["command"] == "print('ok')" and calls["python_destroy"]["context_id"] == "context-a",
          "SDK Python operation did not use official execution and cleanup calls")

    sql = invoke({"operation": "sql.execute", "timeout": 30,
                  "payload": {"warehouse_id": "warehouse-a", "statement": "SELECT :n", "parameters": [
                      {"name": "n", "value": 7, "type": "INT"}]}})
    check(sql["statement_id"] == "statement-a", "SDK Statement Execution response was not returned")
    sql_call = calls["sql_execute"]
    check(sql_call["disposition"].value == "INLINE" and sql_call["format"].value == "JSON_ARRAY",
          "SDK Statement Execution did not use typed official options")
    check(sql_call["parameters"][0].as_dict() == {"name": "n", "type": "INT", "value": "7"},
          "SDK SQL parameters were not converted to the official typed request model")

    for operation, payload in (
        ("clusters.list", {}), ("clusters.get", {"cluster_id": "cluster-a"}),
        ("warehouses.list", {}), ("warehouses.get", {"warehouse_id": "warehouse-a"}),
        ("jobs.list", {}), ("jobs.get", {"job_id": "17"}),
        ("pipelines.list", {}), ("pipelines.get", {"pipeline_id": "pipeline-a"}),
        ("workspace.list", {"path": "/Shared"}),
    ):
        result = invoke({"operation": operation, "payload": payload})
        check(isinstance(result, dict), f"SDK worker did not return structured data for {operation}")
    check(calls["jobs_list"] == {"limit": 200, "expand_tasks": False}
          and calls["pipelines_list"] == {"max_results": 100}
          and calls["workspace_list"] == {"path": "/Shared"},
          "SDK workspace metadata operations did not use their bounded official methods")

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

    prior_release = (ROOT / "docs" / "versions" / "v2.2.md").read_text(encoding="utf-8")
    current_release = (ROOT / "docs" / "versions" / "v2.3.md").read_text(encoding="utf-8")
    check("| Anvil 2.1 `AGENTS.md` | 4,790 | 1,198 | Baseline |" in prior_release, "old harness size is missing from the release report")
    check("| Anvil 2.2 `AGENTS.md` | 3,710 | 928 | 22.5% fewer bytes |" in prior_release, "historical 2.2 harness size is missing from its release report")
    check(f"| Anvil 2.3 | {agents_size:,} | {round(agents_size / 4):,} |" in current_release, "current harness size/token estimate does not match the release report")


def main() -> int:
    isolated_path = os.pathsep.join(dict.fromkeys((str(Path(sys.executable).parent), "/usr/bin", "/bin")))
    path_guard = mock.patch.dict(os.environ, {"PATH": isolated_path, "ANVIL_VSCODE_CLI": "/nonexistent/anvil-test-code"}, clear=False)
    path_guard.start()
    with tempfile.TemporaryDirectory(prefix="anvil-databricks-tests-") as directory:
        temp = Path(directory)
        test_profile_persistence(temp)
        test_cli_environment_auth_without_named_profile(temp)
        test_multiple_profile_selection(temp)
        test_invalid_selected_profile_never_switches(temp)
        test_cli_minimum_and_missing(temp)
        test_cli_install_failure_survives_unsupported_binary(temp)
        test_resource_discovery_and_mutation_safety(temp)
        test_python_execution_and_cleanup(temp)
        test_timeout_cancellation(temp)
        test_sql_execution_bounds_and_errors(temp)
        test_system_catalog_discovery(temp)
        test_provider_resolver_and_path_regression(temp)
        test_provider_state_dry_run_and_installer(temp)
        test_sdk_fallback_routes_core_operations(temp)
        test_sdk_worker_uses_pinned_official_api_contracts()
    test_finops_scenarios()
    test_query_recipes()
    test_repository_harness_and_legacy_scan()
    path_guard.stop()
    print("PASS Databricks profile, execution, offline FinOps, query recipe, harness, and legacy-token checks")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL Databricks offline checks: {exc}", file=sys.stderr)
        raise SystemExit(1)
