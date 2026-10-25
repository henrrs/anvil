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
import shlex
import stat
import subprocess
import sys
import tempfile
import time
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
public_errors = load_module("anvil_public_errors_test", ROOT / "scripts" / "public_errors.py")
dbx.POLL_INTERVAL = 0


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def save_pref(config_home: Path, profile: str = "anvil-dev", host: str = "https://workspace-a.example.invalid") -> None:
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config_home)}, clear=False):
        config_file = config_home / "anvil" / "databricks" / "databrickscfg"
        config_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        config_file.write_text(f"[{profile}]\nhost = {host}\n", encoding="utf-8")
        config_file.chmod(0o600)
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
        "ANVIL_DATABRICKS_SCENARIO": "auth_required",
        "ANVIL_DATABRICKS_FIXTURE_STATE": str(state),
    }
    with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(dbx.sys, "stdin", TTYInput("")), \
            mock.patch("builtins.input", side_effect=["https://workspace-a.example.invalid", "1", "y", "y"]):
        result = dbx.setup()
        human = dbx.presentation.setup_text(result)
        check("Status                 READY" in human and "anvil-dev" in human,
              "successful setup did not present selected profile and readiness")
        check("not on this shell's PATH" in human and str(FIXTURE_BIN) not in human,
              "setup exposed an internal CLI path or omitted its optional PATH note")
        prefs_path = dbx.provider_state.state_path()
        prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
        check(prefs["selected_profile"] == "anvil-dev", "Anvil-owned profile was not selected")
        check(prefs["profile"]["ownership"] == "anvil" and prefs["profile"]["config_file"] == str(dbx.owned_config.config_file()),
              "Anvil profile ownership metadata was not persisted")
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
        config_file = dbx.owned_config.config_file()
        check(config_file.stat().st_mode & 0o777 == 0o600, "Anvil Databricks config is not mode 0600")
        check(config_file.parent.stat().st_mode & 0o777 == 0o700, "Anvil Databricks config directory is not mode 0700")
        dbx.save_preferences("anvil-dev", "https://workspace-a.example.invalid")
        # Resolve again in a new call to show that future sessions reuse the
        # selected profile without selecting another workspace.
        name, host, _ = dbx.resolve_profile()
        check((name, host) == ("anvil-dev", "https://workspace-a.example.invalid"), "selected profile did not persist across calls")
        before = config_file.read_bytes()
        with mock.patch.object(dbx.cli_install, "attempt_cli_install", side_effect=AssertionError("healthy CLI was reinstalled")):
            repeated = dbx.setup()
        check(repeated["selected_profile"] == "anvil-dev" and repeated["already_configured"], "repeat setup changed the selected workspace")
        check(config_file.read_bytes() == before, "idempotent setup rewrote a healthy Anvil config")
        check(json.loads(state.read_text(encoding="utf-8"))["databricks-login"] == 1,
              "idempotent setup repeated interactive Databricks authentication")


def test_cli_environment_auth_without_named_profile(temp: Path) -> None:
    config_home = temp / "environment-auth-config"
    env = {
        "HOME": str(temp / "environment-auth-home"),
        "XDG_CONFIG_HOME": str(config_home),
        "XDG_DATA_HOME": str(temp / "environment-auth-data"),
        "DATABRICKS_CONFIG_FILE": str(temp / "external-databrickscfg"),
        "DATABRICKS_TOKEN": "secret-external-token-must-not-leak",
        "DATABRICKS_HOST": "https://external.workspace.invalid",
        "DATABRICKS_CONFIG_PROFILE": "dev",
        "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
        "ANVIL_DATABRICKS_SCENARIO": "valid",
        "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "environment-auth-state.json"),
        "ANVIL_DATABRICKS_EXECUTION_LOG": str(temp / "environment-auth-execution.jsonl"),
    }
    external = Path(env["DATABRICKS_CONFIG_FILE"])
    external.write_text("[dev]\nhost = https://external.workspace.invalid\n", encoding="utf-8")
    save_pref(config_home)
    with mock.patch.dict(os.environ, env, clear=False):
        selected, host, profiles = dbx.resolve_profile()
        check(selected == "anvil-dev" and host == "https://workspace-a.example.invalid"
              and [item["name"] for item in profiles] == ["anvil-dev"],
              "Anvil did not resolve only its own config profile")
        dbx.discover_clusters()
    calls = [json.loads(line) for line in Path(env["ANVIL_DATABRICKS_EXECUTION_LOG"]).read_text(encoding="utf-8").splitlines()]
    check(calls, "Anvil did not invoke the isolated Databricks CLI")
    for call in calls:
        check(call.get("config_file") == str(config_home / "anvil" / "databricks" / "databrickscfg"),
              f"CLI command did not use Anvil's config: {call}")
        check(call.get("config_profile") == "anvil-dev", "Anvil CLI process did not select its owned profile")
        check("DATABRICKS_TOKEN" not in call.get("databricks_environment_names", [])
              and "DATABRICKS_HOST" not in call.get("databricks_environment_names", []),
              "external credential override names leaked into an Anvil child process")
    check(external.read_text(encoding="utf-8") == "[dev]\nhost = https://external.workspace.invalid\n",
          "Anvil changed the external Databricks configuration")
    check("secret-external-token-must-not-leak" not in repr(calls), "external token appeared in captured command environment")


def test_sdk_environment_uses_owned_config(temp: Path) -> None:
    config_home = temp / "sdk-boundary-config"
    env = {"HOME": str(temp / "sdk-home"), "XDG_CONFIG_HOME": str(config_home),
           "DATABRICKS_CONFIG_FILE": str(temp / "external-sdk-config"),
           "DATABRICKS_CONFIG_PROFILE": "dev", "DATABRICKS_TOKEN": "hidden-sdk-token",
           "DATABRICKS_HOST": "https://external.example.invalid"}
    observed: dict[str, Any] = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["env"] = kwargs["env"]
        return dbx.process.ProcessResult(returncode=0, stdout="{}", stderr="", elapsed_ms=1)

    with mock.patch.dict(os.environ, env, clear=False), \
            mock.patch.object(dbx.sdk, "discover_sdk", return_value={"python": sys.executable}), \
            mock.patch.object(dbx.sdk.process, "run", side_effect=fake_run):
        dbx.sdk.call("identity", profile="anvil-dev")
    child_env = observed["env"]
    check(child_env.get("DATABRICKS_CONFIG_FILE") == str(config_home / "anvil" / "databricks" / "databrickscfg")
          and child_env.get("DATABRICKS_CONFIG_PROFILE") == "anvil-dev",
          "SDK worker did not receive Anvil's config/profile")
    check(not any(key.startswith("DATABRICKS_") and key not in {"DATABRICKS_CONFIG_FILE", "DATABRICKS_CONFIG_PROFILE"}
                  for key in child_env),
          "SDK worker inherited an external Databricks credential override")
    check("hidden-sdk-token" not in repr(observed), "external token was exposed in SDK process diagnostics")


def test_multiple_profile_selection(temp: Path) -> None:
    config_home = temp / "multiple-config"
    external = temp / "external-databrickscfg"
    external.write_text("[dev]\nhost = https://workspace-a.example.invalid\n\n[engineering]\nhost = https://workspace-b.example.invalid\n",
                        encoding="utf-8")
    env = {
        "XDG_CONFIG_HOME": str(config_home),
        "DATABRICKS_CONFIG_FILE": str(external),
        "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
        "ANVIL_DATABRICKS_SCENARIO": "auth_required",
        "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "multiple-state.json"),
    }
    with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(dbx.sys, "stdin", TTYInput("")), \
            mock.patch("builtins.input", side_effect=["https://workspace-c.example.invalid", "1", "y", "y"]), contextlib.redirect_stdout(io.StringIO()):
        result = dbx.setup()
        check(result["selected_profile"] == "anvil-dev", "external profile was adopted instead of creating anvil-dev")
        check(result["workspace_host"] == "https://workspace-c.example.invalid", "new Anvil profile host was mismatched")
        check([item["name"] for item in dbx.discover_profiles()] == ["anvil-dev"],
              "external profiles leaked into Anvil profile discovery")
        doctor = dbx.local_status()
        doctor_text = dbx.status_text(doctor)
        check(doctor["external_profiles_detected"] == 2 and doctor["external_profiles_used"] is False
              and "Used by Anvil        NO" in doctor_text,
              "doctor did not distinguish external profiles from Anvil configuration")
    check(external.read_text(encoding="utf-8").startswith("[dev]"), "external profiles were modified")


def test_invalid_selected_profile_never_switches(temp: Path) -> None:
    config_home = temp / "invalid-config"
    config_home.mkdir()
    state_path = config_home / "anvil" / "databricks.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"schema_version": 2, "selected_profile": "dev",
                                      "workspace_host": "https://workspace-a.example.invalid",
                                      "providers": {}, "capabilities": {}}), encoding="utf-8")
    external = temp / "legacy-databrickscfg"
    external.write_text("[dev]\nhost = https://workspace-a.example.invalid\nauth_type = databricks-cli\n", encoding="utf-8")
    env = {
        "HOME": str(temp),
        "XDG_CONFIG_HOME": str(config_home),
        "DATABRICKS_CONFIG_FILE": str(external),
        "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
        "ANVIL_DATABRICKS_SCENARIO": "auth_required",
        "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "invalid-state.json"),
    }
    with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(dbx.sys, "stdin", TTYInput("")), \
            mock.patch("builtins.input", side_effect=["", "1", "y", "y"]), contextlib.redirect_stdout(io.StringIO()):
        result = dbx.setup()
        check(result["selected_profile"] == "anvil-dev", "legacy external profile was not replaced by Anvil-owned setup")
    check(external.read_text(encoding="utf-8") == "[dev]\nhost = https://workspace-a.example.invalid\nauth_type = databricks-cli\n",
          "migration reauthenticated or modified the legacy external profile")
    state = json.loads((config_home / "anvil" / "databricks.json").read_text(encoding="utf-8"))
    check(state["profile"]["ownership"] == "anvil" and state["selected_profile"] == "anvil-dev",
          "legacy preferences did not switch only after Anvil profile validation")


def test_anvil_config_ownership_and_reset(temp: Path) -> None:
    config_home = temp / "ownership-config"
    external = temp / "ownership-external.cfg"
    external.write_text("[dev]\nhost = https://external.example.invalid\n", encoding="utf-8")
    env = {"HOME": str(temp), "XDG_CONFIG_HOME": str(config_home),
           "DATABRICKS_CONFIG_FILE": str(external),
           "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
           "ANVIL_DATABRICKS_SCENARIO": "valid",
           "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "ownership-fixture-state.json")}
    target = config_home / "anvil" / "databricks" / "databrickscfg"
    with mock.patch.dict(os.environ, env, clear=False):
        target.parent.mkdir(parents=True, mode=0o700)
        target.write_text("[old]\nhost = https://old.example.invalid\n", encoding="utf-8")
        original = target.read_bytes()
        with mock.patch.object(dbx.sys, "stdin", io.StringIO("")):
            try:
                dbx.setup()
            except dbx.DatabricksError as exc:
                check(exc.category == "CONFIG_OWNERSHIP_AMBIGUOUS", "unowned Anvil config had the wrong diagnostic")
            else:
                raise AssertionError("setup adopted an ambiguous Anvil config")
            dry = dbx.setup(dry_run=True)
        check(dry["config_ownership_issue"] == "ambiguous" and target.read_bytes() == original,
              "dry-run did not preserve and diagnose ambiguous configuration")
        target.unlink()
        with mock.patch.object(dbx.sys, "stdin", TTYInput("")), \
                mock.patch("builtins.input", side_effect=["https://workspace-a.example.invalid", "1", "y", "y"]), \
                contextlib.redirect_stdout(io.StringIO()):
            first = dbx.setup()
        check(first["selected_profile"] == "anvil-dev", "clean setup did not create anvil-dev")
        good_config = target.read_bytes()
        target.write_text("[broken\nhost = https://workspace-a.example.invalid\n", encoding="utf-8")
        with mock.patch.object(dbx.sys, "stdin", io.StringIO("")):
            try:
                dbx.setup()
            except dbx.DatabricksError as exc:
                check(exc.category == "CONFIG_INVALID", "corrupt managed config had the wrong diagnostic")
            else:
                raise AssertionError("setup overwrote a corrupt managed config without reset")
        with mock.patch.object(dbx.sys, "stdin", TTYInput("")), \
                mock.patch("builtins.input", side_effect=["", "1", "y", "y"]), \
                contextlib.redirect_stdout(io.StringIO()):
            reset = dbx.setup(reset=True)
        check(reset["selected_profile"] == "anvil-dev" and reset["configuration_backup"],
              "RESET=1 did not revalidate and replace the Anvil-owned configuration")
        backup = Path(reset["configuration_backup"])
        check(backup.is_file() and backup.read_text(encoding="utf-8").startswith("[broken"),
              "reset did not preserve a rollback copy of the prior Anvil config")
        check(target.read_text(encoding="utf-8").startswith("[anvil-dev]") and target.stat().st_mode & 0o777 == 0o600,
              "reset did not install a private Anvil-owned profile")
        check(external.read_text(encoding="utf-8") == "[dev]\nhost = https://external.example.invalid\n",
              "reset changed an external Databricks profile")
        check(good_config.startswith(b"[anvil-dev]") and backup.stat().st_mode & 0o777 == 0o600,
              "Anvil config or reset backup permissions were not private")


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
        check(not value["cli_installed"] and value["overall"] == "NOT_CONFIGURED",
              "missing optional CLI status incorrectly inferred workspace readiness")


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
    timer_value = [94]
    def advancing_time():
        timer_value[0] += 6
        return timer_value[0]
    with mock.patch.dict(os.environ, {**common, "ANVIL_DATABRICKS_SCENARIO": "command_timeout", "ANVIL_DATABRICKS_CALL_LOG": str(log)}, clear=False), \
            mock.patch.object(dbx, "time", type("Timer", (), {"monotonic": staticmethod(advancing_time), "sleep": staticmethod(lambda _value: None)})()):
        try:
            dbx.execute_python("pass", "cluster-a", timeout=5)
        except dbx.DatabricksError as exc:
            check(exc.category == "COMMAND_TIMEOUT", "Python timeout was not classified")
        else:
            raise AssertionError("Python timeout was reported as successful")
    python_calls = Path(log).read_text(encoding="utf-8")
    check("/api/1.2/commands/cancel" in python_calls and "/api/1.2/contexts/destroy" in python_calls, "Python timeout did not cancel and clean up")

    log = temp / "timeout-sql.jsonl"
    timer_value = [94]
    def advancing_time():
        timer_value[0] += 6
        return timer_value[0]
    with mock.patch.dict(os.environ, {**common, "ANVIL_DATABRICKS_SCENARIO": "sql_timeout", "ANVIL_DATABRICKS_CALL_LOG": str(log)}, clear=False), \
            mock.patch.object(dbx, "time", type("Timer", (), {"monotonic": staticmethod(advancing_time), "sleep": staticmethod(lambda _value: None)})()):
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
            check(exc.category == "PERMISSION_DENIED", "permission failure was not categorized")
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
        check(state["overall"] == "READY", "read-only workspace readiness did not pass")
        check(state["system_catalog_reachable"] is None and not state["system_schemas"],
              "readiness unexpectedly required SQL warehouse or system-catalog access")
        check(state["running_all_purpose_compute"] == 1 and state["running_sql_warehouses"] == 1, "resource counts were not reported")
        tables = dbx.execute_sql("SHOW TABLES IN system.billing", "warehouse-a")
        check({row[1] for row in tables["rows"]} == {"usage", "list_prices"}, "live system-table fixture was not returned")
    calls = Path(env["ANVIL_DATABRICKS_CALL_LOG"]).read_text(encoding="utf-8")
    check("SHOW TABLES" not in calls and "SHOW SCHEMAS" not in calls, "system-table SQL was logged")
    denied_env = {**env, "ANVIL_DATABRICKS_SCENARIO": "permission_denied", "ANVIL_DATABRICKS_FIXTURE_STATE": str(Path(env["ANVIL_DATABRICKS_FIXTURE_STATE"]).with_name("catalog-denied-state.json"))}
    with mock.patch.dict(os.environ, denied_env, clear=False):
        denied = dbx.status()
        check(denied["profile_valid"] is True and denied["identity_reachable"] is True, "system-table permission failure invalidated a valid profile")
        check(denied["overall"] == "READY" and denied["system_catalog_reachable"] is None,
              "status readiness was incorrectly coupled to SQL/system-table permission")
        try:
            dbx.execute_sql("SELECT 1", "warehouse-a")
        except dbx.DatabricksError as exc:
            check(exc.category == "PERMISSION_DENIED", "SQL permission limitation did not retain its capability scope")
        else:
            raise AssertionError("SQL succeeded despite the permission-denied fixture")


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
    check(dbx.resolver.overall_state({"cli": {"status": "BLOCKED"}}, {}, auth_valid=False) == "NOT_CONFIGURED",
          "an unavailable optional provider was reported as the overall state before authentication")


def test_documented_cli_grammar() -> None:
    skill = (ROOT / "config" / "skills" / "anvil-databricks" / "SKILL.md").read_text(encoding="utf-8")
    examples = skill.split("```text\n", 1)[1].split("```", 1)[0]
    parser = dbx.build_parser()
    parsed = [parser.parse_args(shlex.split(line)) for line in examples.splitlines() if line.strip()]
    check(len(parsed) >= 14, "Databricks skill lost its documented canonical command examples")
    check(parsed[2].action == "clusters" and parsed[2].resource_action == "list"
          and parsed[2].format == "json", "canonical clusters list syntax does not parse")
    check(parsed[11].action == "python" and parsed[11].timeout == 120,
          "canonical Python command syntax does not parse")
    try:
        parser.parse_args(["clusters", "list", "--format", "yaml"])
    except dbx.DatabricksError as exc:
        check(exc.category == "CLI_ARGUMENT_ERROR", "invalid format was not normalized as a CLI argument error")
    else:
        raise AssertionError("invalid Databricks output format was accepted")


def _fresh_setup_environment(temp: Path, *, scenario: str = "valid") -> dict[str, str]:
    return {
        "HOME": str(temp / f"fresh-{scenario}-home"),
        "XDG_CONFIG_HOME": str(temp / f"fresh-{scenario}-config"),
        "XDG_DATA_HOME": str(temp / f"fresh-{scenario}-data"),
        "PATH": os.pathsep.join((str(Path(sys.executable).parent), "/usr/bin", "/bin")),
        "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
        "ANVIL_DATABRICKS_SCENARIO": scenario,
        "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / f"fresh-{scenario}-fixture-state.json"),
        "ANVIL_DATABRICKS_EXECUTION_LOG": str(temp / f"fresh-{scenario}-provider-execution.jsonl"),
    }


def _complete_fresh_setup(temp: Path, *, scenario: str = "valid") -> dict[str, Any]:
    env = _fresh_setup_environment(temp, scenario=scenario)
    with mock.patch.dict(os.environ, env, clear=False), \
            mock.patch.object(dbx.sys, "stdin", TTYInput("")), \
            mock.patch("builtins.input", side_effect=["https://workspace-a.example.invalid", "1", "y", "y"]), \
            contextlib.redirect_stdout(io.StringIO()):
        result = dbx.setup()
    return result


def test_readiness_state_machine_and_persisted_contract(temp: Path) -> None:
    ready_at = dbx.readiness.now()
    good_capabilities = {
        name: {"supported": True, "available": True, "verified": True, "checked": True,
               "provider": "cli", "validated_at": ready_at, "resource_count": 0}
        for name in dbx.readiness.CORE_CAPABILITIES
    }
    authentication = {"status": "READY", "validated_at": ready_at}
    workspace = {"status": "READY", "validated_at": ready_at}
    provider = {"status": "READY", "selected": "cli", "validation_probe": "current-user + metadata",
                "validated_at": ready_at}
    cases = (
        (False, authentication, workspace, provider, good_capabilities, "NOT_CONFIGURED", "NOT_CONFIGURED"),
        (True, {"status": "FAILED"}, workspace, provider, good_capabilities, "CONFIGURED", "NOT_READY"),
        (True, authentication, {"status": "FAILED"}, provider, good_capabilities, "AUTHENTICATED", "NOT_READY"),
        (True, authentication, workspace, {"status": "FAILED"}, {}, "WORKSPACE_VALIDATED", "NOT_READY"),
        (True, authentication, workspace, provider,
         {**good_capabilities, "compute.list": {"checked": True, "verified": False}},
         "CAPABILITIES_DISCOVERED", "DEGRADED"),
        (True, authentication, workspace, provider, good_capabilities, "READY", "READY"),
    )
    for configured, auth_value, workspace_value, provider_value, capabilities, stage, overall in cases:
        result = dbx.readiness.evaluate(configured=configured, authentication=auth_value,
                                        workspace=workspace_value, provider=provider_value,
                                        capabilities=capabilities)
        check((result["state"], result["overall"]) == (stage, overall),
              f"readiness transition mismatch: expected {(stage, overall)}, got {(result['state'], result['overall'])}")

    state_dir = temp / "readiness-state"
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(state_dir)}, clear=False):
        ready = dbx.readiness.evaluate(configured=True, authentication=authentication,
                                       workspace=workspace, provider=provider,
                                       capabilities=good_capabilities)
        dbx.provider_state.save_state({"readiness": ready})
        invalid = json.loads(json.dumps(ready))
        invalid["capabilities"]["compute.list"]["verified"] = False
        try:
            dbx.provider_state.save_state({"readiness": invalid})
        except ValueError:
            pass
        else:
            raise AssertionError("persisted READY was accepted without verified core capability evidence")


def test_hung_provider_cannot_be_promoted_ready(temp: Path) -> None:
    # Reproduce the baseline defect: its setup summary passed provider inventory
    # to the resolver and treated auth_valid as a proxy for every capability.
    legacy_inventory = {"cli": {"status": "READY"}, "sdk": {"status": "NOT_INSTALLED"}}
    legacy_capabilities = dbx.resolver.resolve(legacy_inventory, auth_valid=True)
    legacy_overall = dbx.resolver.overall_state(legacy_inventory, legacy_capabilities, auth_valid=True)
    check(legacy_overall == "READY",
          "baseline inventory-only readiness reproduction no longer represents the original false-READY behavior")

    env = _fresh_setup_environment(temp, scenario="provider_hang")
    azure_cli_bin = temp / "azure-session-bin"
    azure_cli_bin.mkdir()
    fake_az = azure_cli_bin / "az"
    fake_az.write_text("#!/bin/sh\nif [ \"$1 $2\" = 'account show' ]; then printf '{\\\"id\\\":\\\"fixture-subscription\\\"}\\n'; exit 0; fi\nexit 1\n",
                       encoding="utf-8")
    fake_az.chmod(0o755)
    env["PATH"] = str(azure_cli_bin) + os.pathsep + env["PATH"]
    child_file = temp / "provider-child.pid"
    env["ANVIL_DATABRICKS_CHILD_PID"] = str(child_file)
    original = dbx.timeouts.seconds_for
    budgets = {"workspace_identity": 2, "provider_health": 0.2,
               "metadata_list": 0.2, "process_terminate_grace": 0.1}
    def short_budget(name: str) -> float:
        return budgets.get(name, original(name))
    with mock.patch.dict(os.environ, env, clear=False), \
            mock.patch.object(dbx.timeouts, "seconds_for", side_effect=short_budget), \
            mock.patch.object(dbx.cli_install, "install_sdk",
                              return_value={"status": "BLOCKED", "failure": "policy-blocked",
                                            "message": "network disabled in this offline regression"}), \
            mock.patch.object(dbx.sys, "stdin", TTYInput("")), \
            mock.patch("builtins.input", side_effect=["https://adb-1234567890123456.7.azuredatabricks.net", "1", "y", "y"]), \
            contextlib.redirect_stdout(io.StringIO()):
        result = dbx.setup()
        check(result["overall"] == "NOT_READY", "setup reported READY while its production CLI provider timed out")
        check(result["authentication"]["strategy"] == "azure-cli-session",
              "false-READY fixture did not reproduce a healthy Azure CLI session context")
        check(result["readiness"]["provider"]["status"] == "FAILED"
              and result["readiness"]["provider"]["failure_category"] == "CLI_PROCESS_TIMEOUT",
              "hung production provider did not become an explicit readiness blocker")
        check(result["blockers"][0]["category"] == "CLI_PROCESS_TIMEOUT",
              "setup did not expose the root provider timeout blocker")
        human = dbx.presentation.setup_text(result)
        check("Authentication       READY" in human and "Provider health       FAILED" in human
              and "timed out after 0.2s" in human and "Impact" in human
              and "make databricks-setup" in human and "Anvil has not marked this integration READY." in human,
              "human setup output hid validated stages or failed to explain the provider timeout and repair path")
        doctor_text = dbx.presentation.doctor_text({"overall": result["overall"],
                                                    "readiness": result["readiness"],
                                                    "limitation": "clusters list: CLI_PROCESS_TIMEOUT"})
        check("Root issue" in doctor_text and "timed out after 0.2s" in doctor_text
              and "discovery could not be verified" in doctor_text
              and "make databricks-setup" in doctor_text and "fallback" in doctor_text,
              "human doctor output omitted provider timeout details, impact, or next step")
        active_path = dbx.owned_config.config_file()
        check(not active_path.exists(), f"failed candidate config was promoted to active: {active_path}")
        check(not dbx.provider_state.state_path().exists(), "failed candidate wrote an active provider state")
    check(child_file.is_file(), "hung CLI fixture did not spawn its controlled child process")
    child_pid = int(child_file.read_text(encoding="utf-8"))
    for _ in range(20):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("provider timeout left a child process alive or unreaped")


def test_setup_interruption_preserves_active_configuration(temp: Path) -> None:
    env = _fresh_setup_environment(temp)
    with mock.patch.dict(os.environ, env, clear=False):
        original = _complete_fresh_setup(temp)
        check(original["overall"] == "READY", "interruption fixture did not establish a healthy active config")
        active_path = dbx.owned_config.config_file()
        state_path = dbx.provider_state.state_path()
        active_before = active_path.read_bytes()
        state_before = state_path.read_bytes()

        with mock.patch.object(dbx.sys, "stdin", TTYInput("")), \
                mock.patch("builtins.input", side_effect=["", "1", "y", "y"]), \
                mock.patch.object(dbx, "_setup_summary", side_effect=KeyboardInterrupt), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                dbx.setup(reset=True)
            except KeyboardInterrupt:
                pass
            else:
                raise AssertionError("injected setup interruption was not propagated")

        check(active_path.read_bytes() == active_before,
              "interrupted candidate replaced the previously active Databricks config")
        check(state_path.read_bytes() == state_before,
              "interrupted candidate changed previously active readiness state")
        pending = list(active_path.parent.glob(".databrickscfg.pending.*"))
        check(not pending, f"interrupted setup left candidate config files behind: {pending}")


def test_ready_survives_a_clean_new_process(temp: Path) -> None:
    result = _complete_fresh_setup(temp)
    check(result["overall"] == "READY" and result["readiness"]["state"] == "READY",
          "setup did not reach the complete readiness state")
    setup_text = dbx.presentation.setup_text(result)
    check("Core capabilities discovered" in setup_text
          and "same provider path used by normal Anvil sessions" in setup_text,
          "successful setup did not state that core capabilities used the production session path")
    original_env = _fresh_setup_environment(temp)
    clean_env = {key: value for key, value in os.environ.items()
                 if not key.upper().startswith("DATABRICKS_")}
    clean_env.update(original_env)
    clean_env["PYTHONPATH"] = ""
    script = str(ROOT / "scripts" / "databricks.py")
    status = subprocess.run([sys.executable, script, "status", "--format", "json"],
                            capture_output=True, text=True, env=clean_env, timeout=20, check=False)
    check(status.returncode == 0, f"new process status failed: {status.stderr}")
    status_value = json.loads(status.stdout)
    check(status_value["overall"] == "READY" and status_value["readiness"]["state"] == "READY"
          and status_value["readiness_stale"] is False,
          "clean new process did not reconstruct and revalidate READY state")
    clusters = subprocess.run([sys.executable, script, "clusters", "list", "--format", "json"],
                              capture_output=True, text=True, env=clean_env, timeout=20, check=False)
    check(clusters.returncode == 0, f"new process could not use persisted provider configuration: {clusters.stderr}")
    cluster_value = json.loads(clusters.stdout)
    check(cluster_value["profile"] == "anvil-dev" and cluster_value["running"][0]["cluster_id"] == "cluster-a",
          "new-process workspace operation did not use the persisted Anvil profile")

    doctor = subprocess.run(["make", "--no-print-directory", "doctor"], cwd=ROOT,
                            capture_output=True, text=True, env=clean_env, timeout=30, check=False)
    check(doctor.returncode == 0 and "Overall              READY" in doctor.stdout,
          f"public make doctor did not use the live validated readiness path: {doctor.stdout}\n{doctor.stderr}")

    saved_state_path = Path(original_env["XDG_CONFIG_HOME"]) / "anvil" / "databricks.json"
    state_before_dry_run = saved_state_path.read_bytes()
    setup_dry_run = subprocess.run(["make", "--no-print-directory", "databricks-setup", "DRY_RUN=1", "OUTPUT=json"],
                                   cwd=ROOT, capture_output=True, text=True, env=clean_env,
                                   timeout=30, check=False)
    check(setup_dry_run.returncode == 0, f"public databricks-setup dry-run failed: {setup_dry_run.stderr}")
    plan = json.loads(setup_dry_run.stdout)
    check(plan["dry_run"] is True and plan["profile"] == "anvil-dev"
          and not plan["changes_performed"], "public setup dry-run lost its no-change preview contract")
    check(saved_state_path.read_bytes() == state_before_dry_run,
          "public setup dry-run changed persisted Databricks readiness state")

    capabilities = subprocess.run(["make", "--no-print-directory", "FORMAT=json", "capabilities"], cwd=ROOT,
                                  capture_output=True, text=True, env=clean_env, timeout=30, check=False)
    check(capabilities.returncode == 0, f"public make capabilities failed: {capabilities.stderr}")
    capability_value = json.loads(capabilities.stdout)
    check(capability_value["databricks_capabilities"]["overall"] == "READY"
          and capability_value["databricks_capabilities"]["capabilities"]["compute.list"]["verified"],
          "public local capabilities did not report the persisted recent evidence")


def test_empty_core_lists_and_slow_valid_provider(temp: Path) -> None:
    for scenario, capability in (("empty_clusters", "compute.list"), ("empty_warehouses", "warehouse.list")):
        config_home = temp / f"{scenario}-config"
        config_home.mkdir()
        save_pref(config_home)
        env = {"XDG_CONFIG_HOME": str(config_home),
               "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
               "ANVIL_DATABRICKS_SCENARIO": scenario,
               "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / f"{scenario}-state.json")}
        with mock.patch.dict(os.environ, env, clear=False):
            state = dbx.status()
            item = state["readiness"]["capabilities"][capability]
            check(state["overall"] == "READY" and item["available"] is True
                  and item["verified"] is True and item["resource_count"] == 0,
                  f"successful empty {capability} response was treated as failure")
            public = dbx.capabilities(state)["capabilities"][capability]
            check(public["supported"] is True and public["available"] is True
                  and public["verified"] is True and public["resource_count"] == 0,
                  f"three-dimensional {capability} status lost empty-list evidence")

    config_home = temp / "slow-config"
    config_home.mkdir()
    save_pref(config_home)
    env = {"XDG_CONFIG_HOME": str(config_home), "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
           "ANVIL_DATABRICKS_SCENARIO": "clusters_slow", "ANVIL_DATABRICKS_DELAY_SECONDS": "0.15",
           "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "slow-state.json")}
    original = dbx.timeouts.seconds_for
    with mock.patch.dict(os.environ, env, clear=False), \
            mock.patch.object(dbx.timeouts, "seconds_for",
                              side_effect=lambda name: 0.5 if name in {"workspace_identity", "provider_health", "metadata_list"} else original(name)):
        state = dbx.status()
        check(state["overall"] == "READY" and state["readiness"]["capabilities"]["compute.list"]["verified"],
              "slow but bounded provider response was rejected prematurely")


def test_fallback_and_shared_failure_policy(temp: Path) -> None:
    config_home = temp / "fallback-config"
    config_home.mkdir()
    save_pref(config_home)
    providers = {"cli": {"status": "READY", "executable": str(FIXTURE_BIN / "databricks")},
                 "sdk": {"status": "READY", "python": sys.executable}}

    def cli_timeout(*_args: Any, **_kwargs: Any):
        raise dbx.DatabricksError("CLI_PROCESS_TIMEOUT", "bounded fixture timeout", provider="cli",
                                  operation="clusters list", profile="anvil-dev", timeout_seconds=0.1)
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config_home)}, clear=False), \
            mock.patch.object(dbx, "run_cli", side_effect=cli_timeout), \
            mock.patch.object(dbx.sdk, "call", return_value={"clusters": []}) as sdk_call:
        routed = dbx.json_from_cli(["clusters", "list"], profile="anvil-dev", timeout=0.1,
                                   providers=providers, authentication_strategy="unified-auth",
                                   preferred_provider="cli", with_metadata=True)
    check(routed["provider"] == "sdk" and routed["fallback_reason"] == "CLI_PROCESS_TIMEOUT"
          and routed["rejected_providers"][0]["provider"] == "cli" and sdk_call.call_count == 1,
          "provider-specific CLI timeout did not use and explain SDK fallback")

    malformed_env = {"XDG_CONFIG_HOME": str(config_home),
                     "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
                     "ANVIL_DATABRICKS_SCENARIO": "malformed_clusters",
                     "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "malformed-output-state.json")}
    with mock.patch.dict(os.environ, malformed_env, clear=False), \
            mock.patch.object(dbx.sdk, "call", return_value={"clusters": [{"cluster_id": "sdk-cluster"}]}) as sdk_call:
        routed = dbx.json_from_cli(["clusters", "list"], profile="anvil-dev", timeout=2,
                                   providers=providers, authentication_strategy="unified-auth",
                                   preferred_provider="cli", with_metadata=True)
    check(routed["provider"] == "sdk" and routed["fallback_reason"] == "CLI_OUTPUT_INVALID"
          and routed["value"]["clusters"][0]["cluster_id"] == "sdk-cluster" and sdk_call.call_count == 1,
          "actual CLI fixture malformed JSON did not take the normalized SDK fallback")

    def network_timeout(*_args: Any, **_kwargs: Any):
        raise dbx.DatabricksError("WORKSPACE_NETWORK_TIMEOUT", "shared fixture network failure", provider="cli")
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config_home)}, clear=False), \
            mock.patch.object(dbx, "run_cli", side_effect=network_timeout), \
            mock.patch.object(dbx.sdk, "call", side_effect=AssertionError("shared network failure triggered provider roulette")):
        try:
            dbx.json_from_cli(["clusters", "list"], profile="anvil-dev", timeout=0.1,
                              providers=providers, authentication_strategy="unified-auth",
                              preferred_provider="cli")
        except dbx.DatabricksError as exc:
            check(exc.category == "WORKSPACE_NETWORK_TIMEOUT" and not exc.fallback_allowed,
                  "shared network failure lost its normalized stop policy")
        else:
            raise AssertionError("shared network failure was reported as successful")


def test_setup_installs_sdk_after_cli_health_failure(temp: Path) -> None:
    """An installed CLI is not evidence that a provider-specific request works."""
    config_home = temp / "setup-provider-fallback-config"
    host = "https://workspace-a.example.invalid"
    save_pref(config_home, profile="anvil-prod", host=host)
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config_home)}, clear=False):
        state = dbx.load_preferences()
        state["authentication"] = {"strategy": "azure-cli-session", "provider": "cli", "cloud": "azure"}
        dbx.provider_state.save_state(state)
    env = {
        "XDG_CONFIG_HOME": str(config_home),
        "XDG_DATA_HOME": str(temp / "setup-provider-fallback-data"),
        "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
        "ANVIL_DATABRICKS_SCENARIO": "clusters_timeout",
        "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "setup-provider-fallback-fixture-state.json"),
        "ANVIL_DATABRICKS_EXECUTION_LOG": str(temp / "setup-provider-fallback-cli.jsonl"),
    }
    sdk_installed = False
    fake_sdk_python = temp / "sdk-venv" / "bin" / "python"
    fake_sdk_python.parent.mkdir(parents=True)
    fake_sdk_python.write_text(f"""#!{sys.executable}
import json, sys
if len(sys.argv) > 1 and sys.argv[1] == "-c":
    code = sys.argv[2] if len(sys.argv) > 2 else ""
    if "find_spec" in code:
        raise SystemExit(1)
    print("0.141.0")
    raise SystemExit(0)
request = json.load(sys.stdin)
operation = request.get("operation")
host = "{host}"
if operation == "identity":
    value = {{"identity": {{"userName": "fixture-user"}}, "host": host}}
elif operation == "clusters.list":
    value = {{"clusters": []}}
elif operation == "warehouses.list":
    value = {{"warehouses": []}}
else:
    print(json.dumps({{"error": {{"category": "PROVIDER_UNHEALTHY", "summary": "unexpected fixture operation"}}}}), file=sys.stderr)
    raise SystemExit(1)
print(json.dumps(value))
""", encoding="utf-8")
    fake_sdk_python.chmod(0o700)
    cli_only = {"cli": {"status": "READY", "installed": True,
                         "executable": str(FIXTURE_BIN / "databricks")},
                "sdk": {"status": "NOT_INSTALLED", "installed": False},
                "vscode": {"status": "NOT_INSTALLED"},
                "connect": {"status": "NOT_INSTALLED"},
                "sql_connector": {"status": "NOT_INSTALLED"}}
    with_sdk = {**cli_only, "sdk": {"status": "READY", "installed": True,
                                    "python": str(fake_sdk_python), "version": "0.141.0", "isolated": True}}

    def providers() -> dict[str, Any]:
        return with_sdk if sdk_installed else cli_only

    def install_sdk() -> dict[str, Any]:
        nonlocal sdk_installed
        sdk_installed = True
        return {"status": "READY", "python": str(fake_sdk_python), "version": "0.141.0",
                "isolated": True, "reused": False}

    def sdk_call(operation: str, **_kwargs: Any) -> dict[str, Any]:
        if operation == "identity":
            return {"identity": {"userName": "fixture-user"}, "host": host}
        if operation == "clusters.list":
            return {"clusters": []}
        if operation == "warehouses.list":
            return {"warehouses": []}
        raise AssertionError(f"unexpected SDK operation during setup: {operation}")

    original = dbx.timeouts.seconds_for
    budgets = {"workspace_identity": 1, "provider_health": 0.15,
               "metadata_list": 0.15, "process_terminate_grace": 0.1}
    with mock.patch.dict(os.environ, env, clear=False), \
            mock.patch.object(dbx, "provider_snapshot", side_effect=providers), \
            mock.patch.object(dbx.cli_install, "install_sdk", side_effect=install_sdk) as install, \
            mock.patch.object(dbx.sdk, "call", side_effect=sdk_call) as sdk_execution, \
            mock.patch.object(dbx.timeouts, "seconds_for",
                              side_effect=lambda name: budgets.get(name, original(name))), \
            contextlib.redirect_stdout(io.StringIO()):
        before_config = dbx.owned_config.config_file().read_bytes()
        result = dbx.setup()
        check(install.call_count == 1,
              "explicit setup did not prepare SDK fallback after an installed CLI timed out")
        check(result["overall"] == "READY"
              and result["readiness"]["provider"]["status"] == "READY"
              and result["readiness"]["provider"]["selected"] == "sdk",
              "setup did not revalidate core Databricks operations through the SDK fallback")
        compute = result["readiness"]["capabilities"]["compute.list"]
        warehouses = result["readiness"]["capabilities"]["warehouse.list"]
        check(compute["provider"] == "sdk" and compute["fallback_reason"] == "CLI_PROCESS_TIMEOUT"
              and warehouses["verified"] and sdk_execution.call_count >= 2,
              "fallback did not retain the CLI blocker and validate the SDK production path")
        check(dbx.owned_config.config_file().read_bytes() == before_config,
              "health revalidation rewrote the existing Anvil-owned config")
        saved = dbx.load_preferences()
        check(saved["authentication"]["provider"] == "sdk"
              and saved["providers"]["sdk"]["python"] == str(fake_sdk_python)
              and saved["readiness"]["overall"] == "READY",
              "successful fallback provider was not persisted for a clean future session")
        rendered = dbx.presentation.setup_text(result)
        check("SDK fallback         active" in rendered,
              "setup presentation did not identify the validated fallback provider")
        clean_env = {key: value for key, value in os.environ.items()
                     if not key.upper().startswith("DATABRICKS_")}
        clean_env.update(env)
        clean_env["PYTHONPATH"] = ""
        script = str(ROOT / "scripts" / "databricks.py")
        provider_probe = subprocess.run(
            [sys.executable, "-c",
             "import json,sys; sys.path.insert(0, sys.argv[1]); import databricks; print(json.dumps(databricks.provider_snapshot()))",
             str(ROOT / "scripts")], capture_output=True, text=True, env=clean_env, timeout=10, check=False)
        check(provider_probe.returncode == 0
              and json.loads(provider_probe.stdout)["sdk"]["status"] == "READY",
              f"clean process did not discover the persisted SDK executable: {provider_probe.stdout}\n{provider_probe.stderr}")
        status = subprocess.run([sys.executable, script, "status", "--format", "json"],
                                capture_output=True, text=True, env=clean_env, timeout=20, check=False)
        check(status.returncode == 0, f"fresh process could not load the validated SDK provider: {status.stderr}")
        status_value = json.loads(status.stdout)
        check(status_value["overall"] == "READY"
              and status_value["readiness"]["provider"]["selected"] == "sdk",
              "fresh process did not revalidate the persisted SDK fallback provider")
        clusters = subprocess.run([sys.executable, script, "clusters", "list", "--format", "json"],
                                  capture_output=True, text=True, env=clean_env, timeout=20, check=False)
        check(clusters.returncode == 0 and json.loads(clusters.stdout)["profile"] == "anvil-prod",
              f"fresh process did not route a normal operation through the persisted SDK: {clusters.stdout}\n{clusters.stderr}")


def test_sdk_install_blocker_and_shared_failure_policy_during_setup(temp: Path) -> None:
    config_home = temp / "sdk-install-blocked-config"
    host = "https://workspace-a.example.invalid"
    save_pref(config_home, profile="anvil-prod", host=host)
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config_home)}, clear=False):
        state = dbx.load_preferences()
        state["authentication"] = {"strategy": "azure-cli-session", "provider": "cli", "cloud": "azure"}
        dbx.provider_state.save_state(state)
    env = {"XDG_CONFIG_HOME": str(config_home), "XDG_DATA_HOME": str(temp / "sdk-install-blocked-data"),
           "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
           "ANVIL_DATABRICKS_SCENARIO": "clusters_timeout",
           "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "sdk-install-blocked-state.json")}
    cli_only = {"cli": {"status": "READY", "installed": True,
                         "executable": str(FIXTURE_BIN / "databricks")},
                "sdk": {"status": "NOT_INSTALLED", "installed": False},
                "vscode": {"status": "NOT_INSTALLED"},
                "connect": {"status": "NOT_INSTALLED"},
                "sql_connector": {"status": "NOT_INSTALLED"}}
    original = dbx.timeouts.seconds_for
    budgets = {"workspace_identity": 1, "provider_health": 0.15,
               "metadata_list": 0.15, "process_terminate_grace": 0.1}
    with mock.patch.dict(os.environ, env, clear=False), \
            mock.patch.object(dbx, "provider_snapshot", return_value=cli_only), \
            mock.patch.object(dbx.cli_install, "install_sdk",
                              return_value={"status": "BLOCKED", "failure": "policy-blocked",
                                            "message": "isolated SDK installation was blocked"}) as install, \
            mock.patch.object(dbx.timeouts, "seconds_for",
                              side_effect=lambda name: budgets.get(name, original(name))), \
            contextlib.redirect_stdout(io.StringIO()):
        result = dbx.setup()
    rendered = dbx.presentation.setup_text(result)
    check(install.call_count == 1 and result["overall"] == "NOT_READY"
          and result["providers"]["sdk"]["status"] == "BLOCKED",
          "blocked SDK installation did not retain the unready CLI result")
    check("SDK fallback         blocked" in rendered and "SDK fallback         not needed" not in rendered
          and "could not prepare the isolated SDK fallback" in result["next_step"],
          "setup output concealed that the CLI fallback could not be prepared")

    network_config = temp / "shared-network-setup-config"
    save_pref(network_config, profile="anvil-prod", host=host)
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(network_config)}, clear=False):
        network_state = dbx.load_preferences()
        network_state["authentication"] = {"strategy": "azure-cli-session", "provider": "cli", "cloud": "azure"}
        dbx.provider_state.save_state(network_state)
    network_env = {**env, "XDG_CONFIG_HOME": str(network_config),
                   "XDG_DATA_HOME": str(temp / "shared-network-setup-data"),
                   "ANVIL_DATABRICKS_SCENARIO": "workspace_network_failure",
                   "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "shared-network-setup-state.json")}
    with mock.patch.dict(os.environ, network_env, clear=False), \
            mock.patch.object(dbx, "provider_snapshot", return_value=cli_only), \
            mock.patch.object(dbx.cli_install, "install_sdk",
                              side_effect=AssertionError("shared workspace failure must not install/fallback providers")), \
            contextlib.redirect_stdout(io.StringIO()):
        result = dbx.setup()
    check(result["overall"] == "NOT_READY"
          and result["blockers"][0]["category"] == "WORKSPACE_NETWORK_TIMEOUT",
          "shared network failure was not preserved as the setup blocker")


def test_resource_discovery_uses_metadata_timeout_class() -> None:
    original = dbx.timeouts.seconds_for
    observed: list[str] = []

    def timeout_for(name: str) -> float:
        observed.append(name)
        return {"metadata_list": 37, "provider_health": 19}.get(name, original(name))

    providers = {"cli": {"status": "READY"}, "sdk": {"status": "NOT_INSTALLED"}}
    with mock.patch.object(dbx.timeouts, "seconds_for", side_effect=timeout_for), \
            mock.patch.object(dbx, "json_from_cli", return_value={
                "value": {"clusters": []}, "provider": "cli", "latency_ms": 1,
                "fallback_reason": None, "rejected_providers": []}) as call:
        result = dbx._resource_capability("anvil-dev", "https://workspace-a.example.invalid",
                                          "compute.list", providers, {"strategy": "unified-auth", "provider": "cli"})
    check(result["verified"] and call.call_args.kwargs["timeout"] == 37
          and "metadata_list" in observed and "provider_health" not in observed,
          "cluster inventory used the generic provider-health budget instead of metadata-list policy")


def test_shared_network_auth_and_partial_permission(temp: Path) -> None:
    for scenario, expected_auth in (("workspace_network_failure", "UNKNOWN"), ("auth_invalid", "FAILED")):
        config_home = temp / f"{scenario}-config"
        config_home.mkdir()
        save_pref(config_home)
        log = temp / f"{scenario}-execution.jsonl"
        env = {"XDG_CONFIG_HOME": str(config_home), "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
               "ANVIL_DATABRICKS_SCENARIO": scenario,
               "ANVIL_DATABRICKS_EXECUTION_LOG": str(log),
               "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / f"{scenario}-state.json")}
        with mock.patch.dict(os.environ, env, clear=False):
            state = dbx.status()
            check(state["overall"] == "NOT_READY"
                  and state["readiness"]["authentication"]["status"] == expected_auth,
                  f"{scenario} incorrectly reported a healthy workspace")
            calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            check(not any(item["args"][:2] == ["auth", "login"] for item in calls),
                  f"{scenario} unexpectedly started interactive authentication")
            if scenario == "workspace_network_failure":
                check(state["readiness"]["blockers"][0]["category"] == "WORKSPACE_NETWORK_TIMEOUT"
                      and len(calls) == 1,
                      "shared network blocker did not stop sibling provider/capability probes")

    config_home = temp / "permission-config"
    config_home.mkdir()
    save_pref(config_home)
    env = {"XDG_CONFIG_HOME": str(config_home), "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
           "ANVIL_DATABRICKS_SCENARIO": "permission_denied_clusters",
           "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "permission-state.json")}
    with mock.patch.dict(os.environ, env, clear=False):
        state = dbx.status()
        compute = state["readiness"]["capabilities"]["compute.list"]
        warehouse = state["readiness"]["capabilities"]["warehouse.list"]
        check(state["overall"] == "DEGRADED" and state["readiness"]["provider"]["status"] == "READY"
              and compute["failure_category"] == "PERMISSION_DENIED" and not compute["available"]
              and warehouse["verified"],
              "capability permission denial incorrectly invalidated auth/provider or erased partial access")


def test_expired_auth_invalidates_previous_ready_state(temp: Path) -> None:
    env = _fresh_setup_environment(temp)
    with mock.patch.dict(os.environ, env, clear=False):
        setup_result = _complete_fresh_setup(temp)
        check(setup_result["overall"] == "READY", "auth-expiry fixture did not start READY")
        stale_env = {**env, "ANVIL_DATABRICKS_SCENARIO": "auth_invalid"}
        with mock.patch.dict(os.environ, stale_env, clear=False):
            state = dbx.status()
            check(state["overall"] == "NOT_READY"
                  and state["readiness"]["authentication"]["status"] == "FAILED"
                  and state["readiness"]["authentication"]["failure_category"] == "AUTH_INVALID",
                  "expired workspace authentication left cached readiness READY")
            persisted = dbx.provider_state.load_state()["readiness"]
            check(persisted["overall"] == "NOT_READY"
                  and persisted["authentication"]["status"] == "FAILED",
                  "auth-expiry status failure was not persisted to invalidate old READY evidence")
            with mock.patch.object(dbx.sdk, "call", side_effect=AssertionError("invalid auth triggered provider roulette")):
                try:
                    dbx.json_from_cli(["clusters", "list"], profile="anvil-dev", timeout=2,
                                      providers={"cli": {"status": "READY", "executable": str(FIXTURE_BIN / "databricks")},
                                                 "sdk": {"status": "READY", "python": sys.executable}},
                                      authentication_strategy="unified-auth", preferred_provider="cli")
                except dbx.DatabricksError as exc:
                    check(exc.category == "AUTH_INVALID" and not exc.fallback_allowed,
                          "expired auth did not return the normalized shared-auth failure")
                else:
                    raise AssertionError("expired auth was reported as a successful cluster operation")


def test_process_runner_bounds_output_and_kills_child(temp: Path) -> None:
    oversized = "import sys; sys.stdout.write('a' * 2500000); sys.stderr.write('b' * 2000000)"
    try:
        dbx.process.run([sys.executable, "-c", oversized], env=os.environ, timeout=5)
    except dbx.process.ProcessFailure as exc:
        check(exc.category == "CLI_OUTPUT_INVALID", "oversized subprocess output had the wrong category")
    else:
        raise AssertionError("process runner accepted output beyond its aggregate bound")

    config_home = temp / "process-config"
    config_home.mkdir()
    save_pref(config_home)
    child_file = temp / "runner-child.pid"
    env = {"XDG_CONFIG_HOME": str(config_home), "ANVIL_DATABRICKS_CLI": str(FIXTURE_BIN / "databricks"),
           "ANVIL_DATABRICKS_SCENARIO": "provider_hang", "ANVIL_DATABRICKS_CHILD_PID": str(child_file),
           "ANVIL_DATABRICKS_FIXTURE_STATE": str(temp / "runner-state.json")}
    with mock.patch.dict(os.environ, env, clear=False):
        try:
            dbx.json_from_cli(["clusters", "list"], profile="anvil-dev", timeout=0.2)
        except dbx.DatabricksError as exc:
            check(exc.category == "CLI_PROCESS_TIMEOUT" and exc.provider == "cli"
                  and exc.operation == "clusters list" and exc.timeout_seconds == 0.2
                  and exc.executable == str(FIXTURE_BIN / "databricks")
                  and "0.2s" in str(exc) and "anvil-dev" in str(exc)
                  and "PROVIDER_SPECIFIC" in str(exc),
                  "provider timeout lacked normalized executable-operation context")
        else:
            raise AssertionError("hung provider command unexpectedly completed")
    child_pid = int(child_file.read_text(encoding="utf-8"))
    for _ in range(20):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("subprocess timeout left its spawned child alive or unreaped")

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
        check(old["schema_version"] == 3 and old["selected_profile"] == "engineering", "legacy provider preferences did not migrate to schema 3")
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


def test_topology_auth_strategy_and_presenters() -> None:
    topology = dbx.topology
    strategy = dbx.auth_strategy
    local = topology.detect_topology(environ={"TERM_PROGRAM": "vscode"}, tty=True)
    remote = topology.detect_topology(environ={"VSCODE_AGENT_FOLDER": "/home/user/.vscode-server", "SSH_CONNECTION": "fixture"}, tty=True)
    check(local["kind"] == "vscode_local", "local VS Code terminal was misclassified")
    check(remote["kind"] == "vscode_remote", "VS Code Remote session was misclassified")
    check(topology.detect_topology(environ={"CI": "true"}, tty=False)["kind"] == "headless", "headless session was misclassified")
    check(topology.workspace_cloud("https://adb-123.azuredatabricks.net") == "azure", "Azure host was not detected")
    check(topology.workspace_cloud("https://example.gcp.databricks.com") == "gcp", "GCP host was not detected")
    args = {"topology": remote, "cloud": "azure", "cli_ready": True, "sdk_ready": True,
            "azure_cli_available": True, "azure_cli_authenticated": False}
    check(strategy.resolve(**args)["strategy"] == "azure-cli-device-code", "remote Azure did not select device-code auth")
    check(strategy.resolve(**{**args, "azure_cli_authenticated": True})["strategy"] == "azure-cli-session",
          "existing Azure CLI session was not reused")
    check(strategy.resolve(**{**args, "cloud": "aws"})["strategy"] == "vscode-assisted",
          "remote AWS incorrectly selected browser callback login")
    check(strategy.resolve(**{**args, "cloud": "azure", "topology": local})["strategy"] == "azure-cli-interactive",
          "local Azure without a session did not choose Azure CLI interactive login")
    check(strategy.resolve(**{**args, "cloud": "azure", "topology": local, "azure_cli_available": False})["strategy"] == "databricks-cli-u2m",
          "local Azure without Azure CLI did not retain the Databricks U2M fallback")
    hybrid = topology.detect_topology(environ={"REMOTE_CONTAINERS": "true", "SSH_CONNECTION": "fixture"}, tty=True)
    check(hybrid["kind"] == "unknown_hybrid" and
          strategy.resolve(**{**args, "topology": hybrid})["strategy"] == "azure-cli-device-code",
          "remote hybrid Azure did not choose non-loopback device-code auth")
    check(strategy.resolve(**{**args, "cloud": "aws", "topology": hybrid})["strategy"] == "manual-auth",
          "remote AWS/GCP selected loopback OAuth")
    check(strategy.resolve(**{**args, "topology": local, "cloud": "aws", "sdk_ready": False})["strategy"] == "databricks-cli-u2m",
          "local interactive OAuth path was removed")
    check(strategy.resolve(**{**args, "anvil_profile_valid": True})["strategy"] == "anvil-profile",
          "valid Anvil-owned profile did not take priority")
    connector_only = {"cli": {"status": "NOT_INSTALLED"}, "sdk": {"status": "NOT_INSTALLED"},
                      "sql_connector": {"status": "READY"}, "connect": {"status": "NOT_INSTALLED"},
                      "vscode": {"status": "NOT_INSTALLED"}}
    with mock.patch.object(dbx, "load_preferences", return_value={"authentication": {"strategy": "azure-cli-session", "provider": "sdk"}}):
        azure_routes = dbx.resolve_providers(connector_only, auth_valid=True)
    check(azure_routes["sql.execute"]["state"] == "UNAVAILABLE",
          "SQL Connector OAuth was substituted for an Azure CLI authentication session")
    with mock.patch.object(dbx, "load_preferences", return_value={"authentication": {"strategy": "databricks-cli-u2m", "provider": "cli"}}):
        u2m_routes = dbx.resolve_providers(connector_only, auth_valid=True)
    check(u2m_routes["sql.execute"]["provider"] == "sql_connector",
          "specialized SQL Connector fallback was removed for Databricks OAuth")

    result = {"dry_run": False, "overall": "READY", "selected_profile": "anvil-dev",
              "providers": {"cli": {"status": "READY", "installed": True, "path_visible": False,
                                     "executable": "/internal/private/databricks"},
                            "sdk": {"status": "NOT_INSTALLED"}, "vscode": {"available": True}},
              "authentication": {"strategy": "anvil-profile", "provider": "cli"},
              "topology": {"kind": "local"}}
    rendered = dbx.presentation.setup_text(result)
    check(not rendered.lstrip().startswith("{"), "human setup output begins as JSON")
    check("Status                 READY" in rendered and "development" in rendered,
          "human setup output omitted readiness or profile")
    check("not on this shell's PATH" in rendered, "human setup omitted optional PATH guidance")
    check("/internal/private" not in rendered and "absolute_usable" not in rendered,
          "human setup leaked internal implementation details")
    check("/internal/private/databricks" in dbx.presentation.setup_text(result, verbose=True),
          "verbose mode omitted provider diagnostics")
    blocked_sdk_result = {**result, "overall": "NOT_READY",
                          "providers": {"cli": {"status": "READY", "installed": True},
                                        "sdk": {"status": "BLOCKED", "failure": "pip-unavailable",
                                                "message": "pip is unavailable in Anvil's isolated Python environment."},
                                        "vscode": {"available": False}},
                          "readiness": {}, "next_step": "Resolve the SDK installation blocker, then rerun make databricks-setup."}
    blocked_sdk_text = dbx.presentation.setup_text(blocked_sdk_result)
    check("SDK installation blocker" in blocked_sdk_text and "pip is unavailable" in blocked_sdk_text
          and "Install Python venv/ensurepip support" in blocked_sdk_text,
          "human setup output concealed the missing-pip SDK blocker or remediation")
    phase_result = {**result, "readiness": {"blockers": [{"category": "PERMISSION_DENIED",
                                                             "summary": "clusters list failed",
                                                             "diagnostics": {"phase": "request",
                                                                             "exception_category": "PermissionDenied",
                                                                             "normalized_status": 403}}]}}
    phase_text = dbx.presentation.setup_text(phase_result)
    check("request phase (PermissionDenied), HTTP 403" in phase_text,
          "human setup output omitted safe SDK phase diagnostics")
    doctor_no_profile = dbx.presentation.doctor_text({"overall": "NOT_CONFIGURED", "readiness_stale": False,
                                                       "readiness": {}, "external_profiles_detected": 0,
                                                       "external_profiles_used": False})
    check("cached result is stale" not in doctor_no_profile,
          "doctor presenter marked an unconfigured integration stale")
    remote_result = {"dry_run": False, "overall": "NOT_CONFIGURED", "providers": {},
                     "topology": {"kind": "vscode_remote"}, "authentication": {"strategy": "vscode-assisted"},
                     "next_step": "Sign in with the Databricks VS Code extension, then run make databricks-setup again."}
    remote_text = dbx.presentation.setup_text(remote_result)
    check("vscode remote" in remote_text and "Next step" in remote_text
          and "Status                 READY" not in remote_text,
          "remote no-auth output is not actionable or falsely ready")
    with mock.patch.object(dbx, "setup", return_value=result), mock.patch.object(sys, "argv", ["databricks.py", "setup", "--format", "json"]), contextlib.redirect_stdout(io.StringIO()) as output:
        check(dbx.main() == 0, "JSON setup presenter failed")
    structured = json.loads(output.getvalue())
    check(structured["overall"] == "READY" and "providers" in structured and not output.getvalue().startswith("Databricks Setup"),
          "JSON setup output included human decoration or lost structured provider detail")
    with mock.patch.object(dbx, "setup", return_value={**remote_result, "dry_run": True}), mock.patch.object(sys, "argv", ["databricks.py", "setup", "--dry-run"]), contextlib.redirect_stdout(io.StringIO()) as output:
        check(dbx.main() == 0, "human dry-run presenter failed")
    check("Databricks Setup Plan" in output.getvalue() and not output.getvalue().lstrip().startswith("{"),
          "default dry-run output is not human-readable")
    print("PASS Databricks topology, auth strategy and human presentation contracts")


def test_auth_executor_fakes(temp: Path) -> None:
    cli = temp / "slow-databricks"
    cli.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(3)\n", encoding="utf-8")
    cli.chmod(0o755)
    with mock.patch.object(dbx.auth_executor, "_timeout", return_value=0.05):
        timed = dbx.auth_executor.run_databricks_login(str(cli), "https://workspace.example.invalid")
    check(timed["category"] == "AUTH_TIMEOUT", "stalled CLI login did not time out")
    with mock.patch.object(dbx.auth_executor, "_run_interactive", side_effect=KeyboardInterrupt):
        cancelled = dbx.auth_executor.run_databricks_login(str(cli), "https://workspace.example.invalid")
    check(cancelled["status"] == "CANCELLED" and cancelled["category"] == "AUTH_CANCELLED",
          "login cancellation was not classified")
    bin_dir = temp / "azure-bin"
    bin_dir.mkdir()
    az = bin_dir / "az"
    az.write_text("""#!/bin/sh
if [ "$1 $2" = 'account show' ]; then
  if [ -f "$ANVIL_AZURE_FIXTURE_AUTH" ]; then printf '{"id":"fixture-subscription"}\\n'; exit 0; fi
  exit 1
fi
if [ "$1" = 'login' ]; then
  if [ "$ANVIL_AZURE_FIXTURE_SCENARIO" = 'success' ]; then : > "$ANVIL_AZURE_FIXTURE_AUTH"; printf 'Open the sign-in page and enter code ABCD-EFGH\\n'; exit 0; fi
  exit 1
fi
exit 2
""",
                  encoding="utf-8")
    az.chmod(0o755)
    azure_state = temp / "azure-fixture-authenticated"
    azure_state.unlink(missing_ok=True)
    azure_env = {"PATH": str(bin_dir), "ANVIL_AUTH_TIMEOUT": "10",
                 "ANVIL_AZURE_FIXTURE_AUTH": str(azure_state),
                 "ANVIL_AZURE_FIXTURE_SCENARIO": "success"}
    with mock.patch.dict(os.environ, azure_env, clear=False):
        check(dbx.auth_executor.azure_cli_status(timeout=1) == (True, False),
              "fake Azure CLI unauthenticated state was not detected")
        device = dbx.auth_executor.run_azure_device_login(timeout=1)
    check(device["status"] == "READY", "fake Azure CLI device-code login did not validate")
    azure_state.unlink(missing_ok=True)
    with mock.patch.dict(os.environ, {**azure_env, "ANVIL_AZURE_FIXTURE_SCENARIO": "failure"}, clear=False):
        failed = dbx.auth_executor.run_azure_device_login(timeout=1)
    check(failed["status"] == "FAILED" and failed["category"] == "AUTH_REQUIRED",
          "fake Azure CLI failed login was not classified")
    with mock.patch.dict(os.environ, azure_env, clear=False), \
            mock.patch.object(dbx.auth_executor, "_run_interactive", side_effect=KeyboardInterrupt):
        cancelled_azure = dbx.auth_executor.run_azure_device_login(timeout=1)
    check(cancelled_azure["status"] == "CANCELLED" and cancelled_azure["category"] == "AUTH_CANCELLED",
          "Azure login cancellation was not classified")
    with mock.patch.dict(os.environ, {**azure_env, "DATABRICKS_TOKEN": "hidden-azure-token"}, clear=False), \
            mock.patch.object(dbx.auth_executor, "_run_interactive", return_value={"returncode": 0}) as azure_run, \
            mock.patch.object(dbx.auth_executor, "azure_cli_status", return_value=(True, True)):
        dbx.auth_executor.run_azure_interactive_login(timeout=1)
    check("DATABRICKS_TOKEN" not in azure_run.call_args.kwargs["env"]
          and "hidden-azure-token" not in repr(azure_run.call_args),
          "external Databricks token leaked into Azure CLI login")
    print("PASS auth timeout, cancellation, Azure session states, and device-code execution use local fakes")


def test_setup_auth_orchestration_fakes() -> None:
    host = "https://workspace-a.cloud.databricks.com"
    cli = {"status": "READY", "installed": True, "executable": str(FIXTURE_BIN / "databricks")}
    stage_dir = Path(tempfile.mkdtemp(prefix="anvil-auth-fakes-"))
    config_path = stage_dir / "databrickscfg"
    config_path.write_text("[anvil-dev]\nhost = " + host + "\n", encoding="utf-8")
    decision = {"strategy": "databricks-cli-u2m", "provider": "cli", "auth_required": True}
    with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin", "ANVIL_DATABRICKS_CLI": cli["executable"]}, clear=False), \
            mock.patch.object(dbx, "cli_provider", return_value=cli), \
            mock.patch.object(dbx, "sdk_provider", return_value={"status": "NOT_INSTALLED"}), \
            mock.patch.object(dbx, "_candidate_identity", side_effect=[dbx.DatabricksError("AUTH_REQUIRED", "no auth"), (host, "cli")]) as candidate_identity, \
            mock.patch.object(dbx.auth_executor, "run_databricks_login", return_value={"status": "READY"}) as login:
        auth, selected_host, error = dbx._authenticate_workspace(host, "anvil-dev", config_path,
            {"cli": cli, "sdk": {"status": "NOT_INSTALLED"}}, decision)
    check((selected_host, error) == (host, None) and auth["strategy"] == "databricks-cli-u2m",
          "local CLI OAuth did not validate the Anvil-owned profile")
    check(login.call_args.args[:3] == (cli["executable"], host, "anvil-dev")
          and login.call_args.kwargs["config_path"] == str(config_path),
          "OAuth did not use the selected Anvil profile and staged config")
    check(candidate_identity.call_args.args[2] == config_path,
          "candidate identity validation did not use the staged Anvil config")

    azure_host = "https://adb-123.azuredatabricks.net"
    azure_path = stage_dir / "azure-databrickscfg"
    azure_path.write_text("[anvil-dev]\nhost = " + azure_host + "\n", encoding="utf-8")
    sdk_only = {"cli": {"status": "NOT_INSTALLED"}, "sdk": {"status": "READY", "python": sys.executable}}
    remote_env = {"PATH": "/usr/bin:/bin", "VSCODE_AGENT_FOLDER": "/remote/.vscode-server"}
    with mock.patch.dict(os.environ, remote_env, clear=True), \
            mock.patch.object(dbx, "cli_provider", return_value={"status": "NOT_INSTALLED"}), \
            mock.patch.object(dbx, "sdk_provider", return_value=sdk_only["sdk"]), \
            mock.patch.object(dbx.shutil, "which", side_effect=lambda name: "/usr/bin/az" if name == "az" else None), \
            mock.patch.object(dbx.auth_executor, "run_azure_device_login", return_value={"status": "READY"}) as device_login, \
            mock.patch.object(dbx, "_candidate_identity", side_effect=[dbx.DatabricksError("AUTH_REQUIRED", "not logged in"), (azure_host, "sdk")]) as candidate_identity:
        auth, selected_host, error = dbx._authenticate_workspace(azure_host, "anvil-dev", azure_path,
            sdk_only, {"strategy": "azure-cli-device-code", "provider": "sdk", "auth_required": True})
    check((selected_host, error) == (azure_host, None) and auth["strategy"] == "azure-cli-device-code"
          and device_login.call_count == 1, "remote Azure device-code login was not followed by profile validation")
    check(candidate_identity.call_args.args[:3] == ("anvil-dev", azure_host, azure_path),
          "identity validation did not reuse the Anvil profile/config boundary")
    check("auth_type = azure-cli" in azure_path.read_text(encoding="utf-8"),
          "Azure CLI authentication was not set on the Anvil-owned profile")

    existing_path = stage_dir / "existing-azure-databrickscfg"
    existing_path.write_text("[anvil-dev]\nhost = " + azure_host + "\n", encoding="utf-8")
    with mock.patch.dict(os.environ, remote_env, clear=True), \
            mock.patch.object(dbx, "cli_provider", return_value={"status": "NOT_INSTALLED"}), \
            mock.patch.object(dbx, "sdk_provider", return_value=sdk_only["sdk"]), \
            mock.patch.object(dbx.auth_executor, "run_azure_device_login", side_effect=AssertionError("existing Azure login repeated")), \
            mock.patch.object(dbx.sdk, "call", return_value={"identity": {"id": "fixture-user"}, "host": azure_host}):
        auth, _, error = dbx._authenticate_workspace(azure_host, "anvil-dev", existing_path,
            sdk_only, {"strategy": "azure-cli-session", "provider": "sdk", "auth_required": False})
    check(auth["strategy"] == "azure-cli-session" and error is None,
          "existing Azure CLI session was not reused without another login")
    print("PASS auth orchestration uses Anvil profile/config with local U2M and Azure CLI session/device fakes")


def test_sdk_fallback_routes_core_operations(temp: Path) -> None:
    config_home = temp / "sdk-config"
    config_home.mkdir()
    save_pref(config_home)
    config_file = config_home / "anvil" / "databricks" / "databrickscfg"
    env = {"XDG_CONFIG_HOME": str(config_home), "DATABRICKS_CONFIG_FILE": str(temp / "external-databrickscfg"),
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
            mock.patch.object(dbx, "provider_snapshot", return_value=setup_providers), \
            mock.patch.object(dbx.sdk, "call", side_effect=fake_sdk):
        with mock.patch.object(dbx, "provider_snapshot", return_value=setup_providers), \
                mock.patch.object(dbx.cli_install, "attempt_cli_install", return_value={"status": "BLOCKED", "failure": "policy-blocked"}) as install, \
                mock.patch.object(dbx.cli_install, "install_sdk", side_effect=AssertionError("existing SDK was reinstalled")):
            configured = dbx.setup()
            check(install.call_count == 0, "healthy Anvil SDK profile triggered unnecessary provider installation")
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
            "clusters.get": dbx.json_from_cli(["clusters", "get", "cluster-a"], profile="anvil-dev"),
            "warehouses.get": dbx.json_from_cli(["warehouses", "get", "warehouse-a"], profile="anvil-dev"),
            "jobs.list": dbx.json_from_cli(["jobs", "list"], profile="anvil-dev"),
            "jobs.get": dbx.json_from_cli(["jobs", "get", "17"], profile="anvil-dev"),
            "pipelines.list": dbx.json_from_cli(["pipelines", "list"], profile="anvil-dev"),
            "pipelines.get": dbx.json_from_cli(["pipelines", "get", "pipeline-a"], profile="anvil-dev"),
            "workspace.list": dbx.json_from_cli(["workspace", "list", "/Shared"], profile="anvil-dev"),
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

    client_configurations: list[dict[str, Any]] = []
    workspace_client = types.SimpleNamespace(
        config=types.SimpleNamespace(host="https://adb-123.azuredatabricks.net"),
        current_user=types.SimpleNamespace(me=lambda: {"userName": "fixture-user"}),
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

    class Config:
        def __init__(self, **values):
            self.values = values
            self.host = "https://adb-123.azuredatabricks.net"

    sdk_module = types.ModuleType("databricks.sdk")
    sdk_module.__path__ = []
    sdk_module.WorkspaceClient = lambda **kwargs: (client_configurations.append(kwargs["config"].values) or workspace_client)
    sdk_module.Config = Config
    core_module = types.ModuleType("databricks.sdk.core")
    core_module.Config = Config
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
               "databricks.sdk.core": core_module,
               "databricks.sdk.service": service_module,
               "databricks.sdk.service.compute": compute_module,
               "databricks.sdk.service.sql": sql_module}

    def invoke(request: dict[str, Any], expected_code: int = 0) -> dict[str, Any]:
        request.setdefault("profile", "anvil-dev")
        stdout = io.StringIO()
        stderr = io.StringIO()
        owned_config_path = str(Path(tempfile.gettempdir()) / "anvil-sdk-worker-owned-config")
        with mock.patch.dict(os.environ, {"DATABRICKS_CONFIG_FILE": owned_config_path}, clear=False), \
                mock.patch.dict(sys.modules, modules), mock.patch("sys.stdin", io.StringIO(json.dumps(request))), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = sdk_worker.main()
            check(code == expected_code, f"SDK worker returned an unexpected result for {request['operation']}: {stderr.getvalue()}")
        if expected_code:
            return json.loads(stderr.getvalue())
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
    identity = invoke({"operation": "identity", "payload": {}})
    check(identity["identity"]["userName"] == "fixture-user"
          and client_configurations[-1] == {
              "profile": "anvil-dev", "config_file": str(Path(tempfile.gettempdir()) / "anvil-sdk-worker-owned-config"),
              "http_timeout_seconds": 60, "retry_timeout_seconds": 120},
          "SDK worker did not use the Anvil-owned Unified Authentication profile")
    invoke({"operation": "identity", "profile": "dev", "payload": {}}, expected_code=1)

    original_cluster_list = workspace_client.clusters.list
    workspace_client.clusters.list = lambda: [{"unsafe": {1}}]
    serialization_failure = invoke({"operation": "clusters.list", "payload": {}}, expected_code=1)
    check(serialization_failure["error"]["phase"] == "response_parsing"
          and serialization_failure["error"]["exception_category"] == "TypeError"
          and "unsafe" not in json.dumps(serialization_failure),
          "SDK response-serialization failure lost its safe response phase")
    workspace_client.clusters.list = original_cluster_list

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


def test_sdk_diagnostics_cross_real_worker_process(temp: Path) -> None:
    package = temp / "fake-sdk"
    (package / "databricks" / "sdk" / "service").mkdir(parents=True)
    (package / "databricks" / "__init__.py").write_text("", encoding="utf-8")
    (package / "databricks" / "sdk" / "core.py").write_text("""\
import os
class Config:
    def __init__(self, **values):
        assert values['profile'] == 'anvil-prod'
        assert values['config_file'] == os.environ['DATABRICKS_CONFIG_FILE']
        self.values = values
        self.host = 'https://workspace.example.invalid'
""", encoding="utf-8")
    (package / "databricks" / "sdk" / "__init__.py").write_text("""\
from .core import Config
class PermissionDenied(Exception):
    status_code = 403
class Clusters:
    def list(self):
        raise PermissionDenied('token=fixture-secret workspace=private-fixture')
class WorkspaceClient:
    def __init__(self, *, config):
        self.config = config
        self.clusters = Clusters()
""", encoding="utf-8")
    (package / "databricks" / "sdk" / "service" / "__init__.py").write_text("from . import compute, sql\n", encoding="utf-8")
    (package / "databricks" / "sdk" / "service" / "compute.py").write_text("class Language: PYTHON = 'PYTHON'\n", encoding="utf-8")
    (package / "databricks" / "sdk" / "service" / "sql.py").write_text("pass\n", encoding="utf-8")
    config_file = temp / "owned-databrickscfg"
    config_file.write_text("[anvil-prod]\nhost = https://workspace.example.invalid\n", encoding="utf-8")
    with mock.patch.dict(os.environ, {"PYTHONPATH": os.pathsep.join((str(package), os.environ.get("PYTHONPATH", "")))}, clear=False):
        try:
            dbx.sdk.call("clusters.list", profile="anvil-prod", python=sys.executable,
                         config_path=str(config_file), timeout=3)
        except dbx.DatabricksError as exc:
            check(exc.category == "PERMISSION_DENIED", "SDK subprocess failure category was not normalized")
            check(exc.diagnostics == {"phase": "request", "operation": "clusters.list",
                                      "exception_category": "PermissionDenied", "normalized_status": 403,
                                      "retryable": False, "failure_scope": "CAPABILITY"},
                  "safe SDK phase diagnostics did not cross the worker boundary")
            check("fixture-secret" not in str(exc) and "private-fixture" not in str(exc)
                  and "fixture-secret" not in repr(exc.diagnostics),
                  "SDK worker leaked a secret or arbitrary exception message")
        else:
            raise AssertionError("SDK worker unexpectedly succeeded for a permission failure")


def test_sdk_bootstrap_pip_blocker_and_venv_path_identity(temp: Path) -> None:
    data_home = temp / "sdk-bootstrap-data"
    venv_python = data_home / "anvil" / "databricks" / "venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(sys.executable)
    invocation = str(venv_python.absolute())
    with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(data_home)}, clear=False):
        def missing_pip(command, **kwargs):
            if command[1:3] == ["-c", "import sys; print(sys.prefix)"]:
                return subprocess.CompletedProcess(command, 0, stdout=str(venv_python.parent.parent), stderr="")
            if command[1:3] == ["-c", "import importlib.metadata as m; print(m.version('databricks-sdk'))"]:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
            if command[1:4] == ["-m", "pip", "--version"]:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="No module named pip")
            raise AssertionError(f"unexpected SDK bootstrap command: {command}")

        with mock.patch.object(dbx.cli_install.subprocess, "run", side_effect=missing_pip):
            blocked = dbx.cli_install.install_sdk()
        check(blocked["status"] == "BLOCKED" and blocked["failure"] == "pip-unavailable"
              and "pip is unavailable" in blocked["message"],
              "missing pip was not reported as a structured SDK installation blocker")

        def sdk_present(command, **kwargs):
            check(command[0] == invocation, "SDK bootstrap collapsed the venv interpreter invocation path")
            if command[1:3] == ["-c", "import sys; print(sys.prefix)"]:
                return subprocess.CompletedProcess(command, 0, stdout=str(venv_python.parent.parent), stderr="")
            if command[1:3] == ["-c", "import importlib.metadata as m; print(m.version('databricks-sdk'))"]:
                return subprocess.CompletedProcess(command, 0, stdout="0.141.0\n", stderr="")
            raise AssertionError(f"an installed SDK should not require pip: {command}")

        with mock.patch.object(dbx.cli_install.subprocess, "run", side_effect=sdk_present):
            ready = dbx.cli_install.install_sdk()
        check(ready["status"] == "READY" and ready["python"] == invocation,
              "installed SDK did not retain the venv symlink invocation path")
        with mock.patch.object(dbx.discovery, "python_version", return_value="0.141.0"):
            discovered = dbx.discovery.discover_sdk({"providers": {"sdk": {"python": invocation}}})
        check(discovered["python"] == invocation and discovered["environment"] == "verified-state",
              "SDK discovery resolved the venv symlink to the system interpreter")


def test_public_error_boundary_redacts_and_keeps_debug_frames() -> None:
    def explode() -> int:
        raise RuntimeError("token=fixture-secret; unexpected worker data")

    normal = io.StringIO()
    with contextlib.redirect_stderr(normal):
        code = public_errors.run_public(explode, command="Anvil test command")
    check(code == 1 and "unexpected internal error" in normal.getvalue()
          and "Traceback" not in normal.getvalue() and "fixture-secret" not in normal.getvalue(),
          "public exception boundary leaked traceback content or secrets")
    debug = io.StringIO()
    with mock.patch.dict(os.environ, {"DEBUG": "1"}, clear=False), contextlib.redirect_stderr(debug):
        code = public_errors.run_public(explode, command="Anvil test command")
    check(code == 1 and "Debug traceback" in debug.getvalue() and "RuntimeError" in debug.getvalue()
          and "fixture-secret" not in debug.getvalue(),
          "DEBUG mode did not preserve a safe traceback")

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
    current_release = (ROOT / "docs" / "versions" / "v2.6.0.md").read_text(encoding="utf-8")
    check("| Anvil 2.1 `AGENTS.md` | 4,790 | 1,198 | Baseline |" in prior_release, "old harness size is missing from the release report")
    check("| Anvil 2.2 `AGENTS.md` | 3,710 | 928 | 22.5% fewer bytes |" in prior_release, "historical 2.2 harness size is missing from its release report")
    check(f"| Anvil 2.6 | {agents_size:,} | {round(agents_size / 4):,} |" in current_release,
          "current harness size/token estimate does not match the release report")


def main() -> int:
    isolated_path = os.pathsep.join(dict.fromkeys((str(Path(sys.executable).parent), "/usr/bin", "/bin")))
    path_guard = mock.patch.dict(os.environ, {"PATH": isolated_path, "ANVIL_VSCODE_CLI": "/nonexistent/anvil-test-code"}, clear=False)
    path_guard.start()
    with tempfile.TemporaryDirectory(prefix="anvil-databricks-tests-") as directory:
        temp = Path(directory)
        test_profile_persistence(temp)
        test_cli_environment_auth_without_named_profile(temp)
        test_sdk_environment_uses_owned_config(temp)
        test_multiple_profile_selection(temp)
        test_invalid_selected_profile_never_switches(temp)
        test_anvil_config_ownership_and_reset(temp)
        test_cli_minimum_and_missing(temp)
        test_cli_install_failure_survives_unsupported_binary(temp)
        test_resource_discovery_and_mutation_safety(temp)
        test_python_execution_and_cleanup(temp)
        test_timeout_cancellation(temp)
        test_sql_execution_bounds_and_errors(temp)
        test_system_catalog_discovery(temp)
        test_provider_resolver_and_path_regression(temp)
        test_documented_cli_grammar()
        test_readiness_state_machine_and_persisted_contract(temp)
        test_hung_provider_cannot_be_promoted_ready(temp)
        test_setup_interruption_preserves_active_configuration(temp)
        test_ready_survives_a_clean_new_process(temp)
        test_empty_core_lists_and_slow_valid_provider(temp)
        test_fallback_and_shared_failure_policy(temp)
        test_setup_installs_sdk_after_cli_health_failure(temp)
        test_sdk_install_blocker_and_shared_failure_policy_during_setup(temp)
        test_resource_discovery_uses_metadata_timeout_class()
        test_shared_network_auth_and_partial_permission(temp)
        test_expired_auth_invalidates_previous_ready_state(temp)
        test_process_runner_bounds_output_and_kills_child(temp)
        test_provider_state_dry_run_and_installer(temp)
        test_sdk_bootstrap_pip_blocker_and_venv_path_identity(temp)
        test_topology_auth_strategy_and_presenters()
        test_auth_executor_fakes(temp)
        test_setup_auth_orchestration_fakes()
        test_sdk_fallback_routes_core_operations(temp)
        test_sdk_worker_uses_pinned_official_api_contracts()
        test_sdk_diagnostics_cross_real_worker_process(temp)
        test_public_error_boundary_redacts_and_keeps_debug_frames()
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
