#!/usr/bin/env python3
"""Secret-safe Databricks CLI adapter used by Anvil and its Databricks skill."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit


MINIMUM_CLI = (1, 0, 0)
MAX_SQL_ROWS = 100
MAX_SQL_BYTES = 1_000_000
MAX_RESULT_BYTES = 1_000_000
MAX_REMOTE_CODE_BYTES = 1_000_000
DEFAULT_TIMEOUT = 120
POLL_INTERVAL = 1.0


class DatabricksError(RuntimeError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def preferences_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "anvil" / "databricks.json"


def load_preferences() -> dict[str, Any]:
    path = preferences_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DatabricksError("PREFERENCES_INVALID", f"Anvil Databricks preferences cannot be read: {path}") from exc
    if not isinstance(value, dict):
        raise DatabricksError("PREFERENCES_INVALID", "Anvil Databricks preferences must be a JSON object")
    forbidden = {"token", "access_token", "refresh_token", "password", "client_secret", "secret", "credential", "credentials"}

    def contains_credential_field(item: Any) -> bool:
        if isinstance(item, dict):
            return any(key.casefold() in forbidden or contains_credential_field(child) for key, child in item.items())
        if isinstance(item, list):
            return any(contains_credential_field(child) for child in item)
        return False

    if contains_credential_field(value):
        raise DatabricksError("PREFERENCES_INVALID", "Anvil preferences contain a credential field; remove it and authenticate through the Databricks CLI")
    return value


def save_preferences(profile: str, host: str) -> Path:
    safe_host = workspace_host(host)
    value = {
        "schema_version": 1,
        "selected_profile": profile,
        "workspace_host": safe_host,
        "last_verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=".databricks.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path


def workspace_host(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise DatabricksError("WORKSPACE_PROFILE_INVALID", "profile does not contain a safe HTTPS workspace URL")
    if parsed.hostname.casefold() in {"accounts.cloud.databricks.com", "accounts.azuredatabricks.net"}:
        raise DatabricksError("ACCOUNT_PROFILE_UNSUPPORTED", "account-level profiles cannot be used for workspace operations")
    return f"https://{parsed.netloc}"


def cli_binary() -> str | None:
    override = os.environ.get("ANVIL_DATABRICKS_CLI")
    if override:
        return override if Path(override).is_file() and os.access(override, os.X_OK) else None
    return shutil.which("databricks")


def parse_version(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"(?<!\d)v?(\d+)\.(\d+)\.(\d+)(?!\d)", value)
    return tuple(map(int, match.groups())) if match else None


def cli_version() -> tuple[str | None, tuple[int, int, int] | None]:
    binary = cli_binary()
    if not binary:
        return None, None
    try:
        result = subprocess.run([binary, "-v"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return "unknown", None
    output = (result.stdout or result.stderr).strip().splitlines()
    raw = output[0] if output else "unknown"
    version = parse_version(raw)
    return (".".join(map(str, version)) if version else raw[:80]), version


def require_cli() -> tuple[str, str]:
    binary = cli_binary()
    if not binary:
        raise DatabricksError("CLI_MISSING", "Databricks CLI is not installed; see https://docs.databricks.com/aws/en/dev-tools/cli/install")
    version_text, version = cli_version()
    if version is None:
        raise DatabricksError("CLI_VERSION_UNKNOWN", "Databricks CLI version could not be identified")
    if version < MINIMUM_CLI:
        raise DatabricksError("CLI_TOO_OLD", f"Databricks CLI {version_text} is below Anvil's supported minimum 1.0.0")
    return binary, version_text or "unknown"


def run_cli(arguments: list[str], *, profile: str | None = None, timeout: float = 20, stdin: str | None = None) -> str:
    binary, _ = require_cli()
    command = [binary, *arguments]
    if profile:
        command.extend(["--profile", profile])
    try:
        result = subprocess.run(command, input=stdin, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise DatabricksError("CLI_TIMEOUT", "Databricks CLI request timed out") from exc
    except OSError as exc:
        raise DatabricksError("CLI_UNAVAILABLE", "Databricks CLI could not be started") from exc
    if result.returncode != 0:
        # CLI errors may contain user data. Keep the diagnostic categorical and
        # never forward raw stdout/stderr, debug output, or credential values.
        detail = "authentication or permission error" if result.returncode in (3, 4, 5) else "request failed"
        raise DatabricksError("CLI_REQUEST_FAILED", f"Databricks CLI {detail} (exit {result.returncode})")
    return result.stdout.strip()


def parse_profiles(output: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        data = None
    profiles: list[dict[str, Any]] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("Name")
            host = item.get("host") or item.get("Host")
            valid = item.get("valid", item.get("Valid", False))
            if name and host:
                profiles.append({"name": str(name), "host": str(host), "valid": valid is True or str(valid).casefold() in {"yes", "true", "valid"}})
        return profiles
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[0].casefold() == "name" or not parts[-1].casefold() in {"yes", "no", "true", "false"}:
            continue
        host = " ".join(parts[1:-1])
        profiles.append({"name": parts[0], "host": host, "valid": parts[-1].casefold() in {"yes", "true"}})
    return profiles


def discover_profiles(timeout: float = 60) -> list[dict[str, Any]]:
    output = run_cli(["auth", "profiles"], timeout=timeout)
    profiles = parse_profiles(output)
    for profile in profiles:
        try:
            profile["workspace_host"] = workspace_host(profile["host"])
            profile["workspace"] = True
        except DatabricksError:
            profile["workspace_host"] = None
            profile["workspace"] = False
    return profiles


def profile_by_name(profiles: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((item for item in profiles if item["name"] == name), None)


def validate_selected_profile(name: str, listed: dict[str, Any]) -> str:
    if not listed.get("workspace"):
        raise DatabricksError("WORKSPACE_PROFILE_INVALID", "selected profile is not a workspace profile")
    if not listed.get("valid"):
        raise DatabricksError("PROFILE_INVALID", f"selected profile '{name}' is invalid; repair its Databricks CLI authentication")
    described = run_cli(["auth", "describe"], profile=name, timeout=15)
    host_match = re.search(r"(?im)^\s*Host:\s*(https://[^\s]+)\s*$", described)
    if not host_match:
        raise DatabricksError("PROFILE_INVALID", "selected profile did not report a workspace host")
    host = workspace_host(host_match.group(1))
    if host != listed["workspace_host"]:
        raise DatabricksError("PROFILE_CHANGED", "selected profile host changed; run make databricks-setup to review it")
    # This command verifies the selected profile identity without requesting
    # or displaying sensitive CLI output.
    identity = run_cli(["current-user", "me", "--output", "json"], profile=name, timeout=20)
    try:
        identity_data = json.loads(identity)
    except json.JSONDecodeError as exc:
        raise DatabricksError("IDENTITY_INVALID", "Databricks current-user response was not valid JSON") from exc
    if not isinstance(identity_data, dict) or not (identity_data.get("userName") or identity_data.get("id") or identity_data.get("applicationId")):
        raise DatabricksError("IDENTITY_INVALID", "Databricks current-user response did not identify the active principal")
    return host


def resolve_profile(explicit: str | None = None) -> tuple[str, str, list[dict[str, Any]]]:
    require_cli()
    prefs = load_preferences()
    selected = explicit or prefs.get("selected_profile")
    if not selected:
        raise DatabricksError("PROFILE_NOT_SELECTED", "no Anvil Databricks profile is selected; run make databricks-setup")
    profiles = discover_profiles()
    listed = profile_by_name(profiles, str(selected))
    if listed is None:
        raise DatabricksError("PROFILE_MISSING", f"selected Databricks profile '{selected}' is missing; authenticate it, then run make databricks-setup")
    host = validate_selected_profile(str(selected), listed)
    return str(selected), host, profiles


def json_from_cli(arguments: list[str], *, profile: str, timeout: float = 20) -> Any:
    output = run_cli([*arguments, "--output", "json"], profile=profile, timeout=timeout)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise DatabricksError("CLI_RESPONSE_INVALID", "Databricks CLI returned invalid JSON") from exc


def api_call(method: str, path: str, *, profile: str, body: dict[str, Any] | None = None, timeout: float = 30) -> Any:
    if method not in {"get", "post"}:
        raise DatabricksError("API_METHOD_UNSUPPORTED", "Anvil only uses read operations and execution lifecycle endpoints")
    args = ["api", method, path]
    temporary_dir = None
    if body is not None:
        temporary_dir = tempfile.TemporaryDirectory(prefix="anvil-databricks-")
        os.chmod(temporary_dir.name, 0o700)
        body_path = Path(temporary_dir.name) / "request.json"
        body_path.write_text(json.dumps(body, separators=(",", ":")), encoding="utf-8")
        os.chmod(body_path, 0o600)
        args.extend(["--json", "@" + str(body_path)])
    args.extend(["--output", "json"])
    try:
        output = run_cli(args, profile=profile, timeout=timeout)
    finally:
        if temporary_dir:
            temporary_dir.cleanup()
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise DatabricksError("API_RESPONSE_INVALID", "Databricks API response was not valid JSON") from exc


def item_list(value: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
    return []


def normalized_cluster(cluster: dict[str, Any]) -> dict[str, Any] | None:
    source = str(cluster.get("cluster_source") or "").upper()
    if source not in {"UI", "API"} or cluster.get("is_job_cluster") is True:
        return None
    autoscale = cluster.get("autoscale") if isinstance(cluster.get("autoscale"), dict) else {}
    return {
        "cluster_id": cluster.get("cluster_id"),
        "cluster_name": cluster.get("cluster_name"),
        "state": str(cluster.get("state") or "UNKNOWN").upper(),
        "cluster_source": source,
        "spark_version": cluster.get("spark_version"),
        "worker_node_type_id": cluster.get("node_type_id"),
        "driver_node_type_id": cluster.get("driver_node_type_id"),
        "num_workers": cluster.get("num_workers"),
        "autoscale_min_workers": autoscale.get("min_workers"),
        "autoscale_max_workers": autoscale.get("max_workers"),
        "state_message": None,
    }


def discover_clusters(profile: str | None = None) -> dict[str, Any]:
    selected, host, _ = resolve_profile(profile)
    data = json_from_cli(["clusters", "list"], profile=selected, timeout=30)
    clusters = [item for raw in item_list(data, "clusters") if (item := normalized_cluster(raw))]
    running = [item for item in clusters if item["state"] == "RUNNING" and item.get("cluster_id")]
    stopped = [item for item in clusters if item["state"] in {"TERMINATED", "STOPPED"} and item.get("cluster_id")]
    return {
        "profile": selected, "workspace_host": host, "running": running, "stopped": stopped,
        "selection_required": len(running) > 1,
        "approval_required_to_start": not running and bool(stopped),
        "remote_python_available": bool(running),
    }


def normalized_warehouse(warehouse: dict[str, Any]) -> dict[str, Any] | None:
    identifier = warehouse.get("id") or warehouse.get("warehouse_id")
    if not identifier:
        return None
    return {
        "warehouse_id": identifier,
        "name": warehouse.get("name") or warehouse.get("warehouse_name"),
        "state": str(warehouse.get("state") or "UNKNOWN").upper(),
        "warehouse_type": warehouse.get("warehouse_type") or warehouse.get("type"),
        "size": warehouse.get("cluster_size") or warehouse.get("warehouse_size"),
        "min_clusters": warehouse.get("min_num_clusters") or warehouse.get("min_clusters"),
        "max_clusters": warehouse.get("max_num_clusters") or warehouse.get("max_clusters"),
        "auto_stop_minutes": warehouse.get("auto_stop_mins") or warehouse.get("auto_stop_minutes"),
    }


def discover_warehouses(profile: str | None = None) -> dict[str, Any]:
    selected, host, _ = resolve_profile(profile)
    data = json_from_cli(["warehouses", "list"], profile=selected, timeout=30)
    warehouses = [item for raw in item_list(data, "warehouses", "endpoints") if (item := normalized_warehouse(raw))]
    running = [item for item in warehouses if item["state"] == "RUNNING"]
    stopped = [item for item in warehouses if item["state"] in {"STOPPED", "STOPPING"}]
    return {
        "profile": selected, "workspace_host": host, "running": running, "stopped": stopped,
        "selection_required": len(running) > 1,
        "approval_required_to_start": not running and bool(stopped),
        "sql_available": bool(running),
    }


def bounded_result(value: Any, byte_limit: int = MAX_RESULT_BYTES) -> Any:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= byte_limit:
        return value
    if isinstance(value, dict):
        result = dict(value)
        rows = result.get("rows")
        if isinstance(rows, list):
            bounded = []
            for row in rows:
                if len(json.dumps(bounded + [row], ensure_ascii=False).encode("utf-8")) > byte_limit // 2:
                    break
                bounded.append(row)
            result["rows"] = bounded
            result["truncated"] = True
            result["omitted_rows"] = max(0, len(rows) - len(bounded))
            return result
    return {"truncated": True, "message": "Remote result exceeded Anvil's local output limit"}


def sql_result(response: dict[str, Any]) -> dict[str, Any]:
    status = response.get("status") if isinstance(response.get("status"), dict) else {}
    state = str(status.get("state") or "UNKNOWN").upper()
    if state == "FAILED":
        error = status.get("error") if isinstance(status.get("error"), dict) else {}
        code = str(error.get("error_code") or "QUERY_FAILED")
        raise DatabricksError("STATEMENT_FAILED", f"Databricks SQL statement failed ({code})")
    if state in {"CANCELED", "CLOSED"}:
        raise DatabricksError("STATEMENT_" + state, f"Databricks SQL statement ended with state {state}")
    if state != "SUCCEEDED":
        return {"statement_id": response.get("statement_id"), "state": state}
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    manifest = response.get("manifest") if isinstance(response.get("manifest"), dict) else {}
    schema = manifest.get("schema") if isinstance(manifest.get("schema"), dict) else result.get("schema", {})
    columns = schema.get("columns", []) if isinstance(schema, dict) else []
    data_array = result.get("data_array", []) if isinstance(result.get("data_array"), list) else []
    output = {
        "statement_id": response.get("statement_id"), "state": state,
        "columns": [column.get("name") for column in columns if isinstance(column, dict)],
        "rows": data_array[:MAX_SQL_ROWS],
        "truncated": bool(result.get("truncated") or len(data_array) > MAX_SQL_ROWS),
    }
    return bounded_result(output)


def sql_may_mutate(statement: str) -> bool:
    without_comments = re.sub(r"/\*.*?\*/|--[^\r\n]*", " ", statement, flags=re.S)
    without_literals = re.sub(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"", " ", without_comments)
    writes = r"\b(?:INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|COPY|LOAD|EXPORT|IMPORT|OPTIMIZE|VACUUM|REFRESH|CALL|EXECUTE|EXEC|RESTORE|REPAIR|REPLACE|RENAME|COMMENT|MSCK|RESET|SET|USE|CACHE|UNCACHE)\b"
    return bool(re.search(writes, without_literals, flags=re.I))


def execute_sql(statement: str, warehouse_id: str, profile: str | None = None, parameters: list[dict[str, Any]] | None = None, timeout: int = DEFAULT_TIMEOUT, allow_mutation: bool = False) -> dict[str, Any]:
    selected, _, _ = resolve_profile(profile)
    if len(statement.encode("utf-8")) > MAX_REMOTE_CODE_BYTES:
        raise DatabricksError("STATEMENT_TOO_LARGE", "SQL statement exceeds Anvil's 1 MB limit")
    if sql_may_mutate(statement) and not allow_mutation:
        raise DatabricksError("SQL_MUTATION_APPROVAL_REQUIRED", "statement may change remote data or configuration; obtain direct user approval, then explicitly pass --allow-mutation")
    found = discover_warehouses(selected)
    warehouse = next((item for item in [*found["running"], *found["stopped"]] if item["warehouse_id"] == warehouse_id), None)
    if warehouse is None:
        raise DatabricksError("WAREHOUSE_NOT_FOUND", "requested warehouse is not visible to the selected profile")
    if warehouse["state"] != "RUNNING":
        raise DatabricksError("WAREHOUSE_STOPPED", "selected warehouse is stopped; user approval is required before starting it")
    body: dict[str, Any] = {
        "statement": statement,
        "warehouse_id": warehouse_id,
        "wait_timeout": "10s",
        "on_wait_timeout": "CONTINUE",
        "disposition": "INLINE",
        "format": "JSON_ARRAY",
        "row_limit": MAX_SQL_ROWS,
        "byte_limit": MAX_SQL_BYTES,
    }
    if parameters:
        body["parameters"] = parameters
    response = api_call("post", "/api/2.0/sql/statements", profile=selected, body=body)
    statement_id = response.get("statement_id") if isinstance(response, dict) else None
    if not statement_id:
        raise DatabricksError("STATEMENT_SUBMIT_FAILED", "Databricks did not return a statement identifier")
    deadline = time.monotonic() + max(5, min(timeout, 600))
    current = response
    while True:
        result = sql_result(current)
        if result["state"] == "SUCCEEDED":
            return result
        if result["state"] not in {"PENDING", "RUNNING"}:
            return result
        if time.monotonic() >= deadline:
            try:
                api_call("post", f"/api/2.0/sql/statements/{statement_id}/cancel", profile=selected, body={})
            except DatabricksError:
                pass
            raise DatabricksError("STATEMENT_TIMEOUT", "Databricks SQL statement timed out and cancellation was requested")
        time.sleep(POLL_INTERVAL)
        current = api_call("get", f"/api/2.0/sql/statements/{statement_id}", profile=selected, timeout=20)


def api_json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def command_result(response: dict[str, Any]) -> dict[str, Any] | None:
    state = str(response.get("status") or "UNKNOWN")
    if state == "Finished":
        results = response.get("results") if isinstance(response.get("results"), dict) else {}
        return bounded_result({"state": state, "result_type": results.get("resultType"), "data": results.get("data"), "truncated": bool(results.get("truncated"))})
    if state in {"Error", "Canceled", "Cancelled"}:
        raise DatabricksError("COMMAND_" + state.upper(), f"Databricks Python command ended with state {state}")
    if state not in {"Queued", "Running", "Pending"}:
        raise DatabricksError("COMMAND_STATE_UNKNOWN", f"Databricks Python command returned unexpected state {state}")
    return None


def execute_python(code: str, cluster_id: str, profile: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    selected, _, _ = resolve_profile(profile)
    if not code.strip():
        raise DatabricksError("CODE_EMPTY", "Python code is empty")
    if len(code.encode("utf-8")) > MAX_REMOTE_CODE_BYTES:
        raise DatabricksError("CODE_TOO_LARGE", "Python code exceeds Anvil's 1 MB limit")
    clusters = discover_clusters(selected)
    cluster = next((item for item in [*clusters["running"], *clusters["stopped"]] if item["cluster_id"] == cluster_id), None)
    if cluster is None:
        raise DatabricksError("CLUSTER_NOT_FOUND", "requested cluster is not visible or is not classic all-purpose compute")
    if cluster["state"] != "RUNNING":
        raise DatabricksError("CLUSTER_STOPPED", "selected cluster is stopped; user approval is required before starting it")
    context_id = None
    command_id = None
    deadline = time.monotonic() + max(5, min(timeout, 600))
    try:
        context = api_call("post", "/api/1.2/contexts/create", profile=selected, body={"clusterId": cluster_id, "language": "python"})
        context_id = context.get("id") if isinstance(context, dict) else None
        if not context_id:
            raise DatabricksError("CONTEXT_CREATE_FAILED", "Databricks did not return an execution context identifier")
        while True:
            context_status = api_call("get", "/api/1.2/contexts/status?" + urlencode({"clusterId": cluster_id, "contextId": context_id}), profile=selected, timeout=20)
            state = str(context_status.get("status") or "UNKNOWN") if isinstance(context_status, dict) else "UNKNOWN"
            if state == "Running":
                break
            if state == "Error":
                raise DatabricksError("CONTEXT_FAILED", "Databricks Python execution context failed to start")
            if time.monotonic() >= deadline:
                raise DatabricksError("CONTEXT_TIMEOUT", "Databricks Python execution context timed out while starting")
            time.sleep(POLL_INTERVAL)
        started = api_call("post", "/api/1.2/commands/execute", profile=selected, body={"clusterId": cluster_id, "contextId": context_id, "language": "python", "command": code})
        command_id = started.get("id") if isinstance(started, dict) else None
        if not command_id:
            raise DatabricksError("COMMAND_SUBMIT_FAILED", "Databricks did not return a Python command identifier")
        while True:
            current = api_call("get", "/api/1.2/commands/status?" + urlencode({"clusterId": cluster_id, "contextId": context_id, "commandId": command_id}), profile=selected, timeout=20)
            result = command_result(current if isinstance(current, dict) else {})
            if result is not None:
                return result
            if time.monotonic() >= deadline:
                try:
                    api_call("post", "/api/1.2/commands/cancel", profile=selected, body={"clusterId": cluster_id, "contextId": context_id, "commandId": command_id})
                except DatabricksError:
                    pass
                raise DatabricksError("COMMAND_TIMEOUT", "Databricks Python command timed out and cancellation was requested")
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt as exc:
        if context_id and command_id:
            try:
                api_call("post", "/api/1.2/commands/cancel", profile=selected, body={"clusterId": cluster_id, "contextId": context_id, "commandId": command_id})
            except DatabricksError:
                pass
        raise DatabricksError("COMMAND_CANCELED", "Databricks Python execution was interrupted") from exc
    finally:
        if context_id:
            try:
                api_call("post", "/api/1.2/contexts/destroy", profile=selected, body={"clusterId": cluster_id, "contextId": context_id}, timeout=20)
            except DatabricksError:
                pass


def read_only_setup_message() -> str:
    return "Install or update using the official guide https://docs.databricks.com/aws/en/dev-tools/cli/install, then run make databricks-setup. Anvil leaves existing CLI installations unchanged."


def choose_profile(profiles: list[dict[str, Any]], previous: str | None) -> dict[str, Any]:
    workspaces = [item for item in profiles if item.get("workspace")]
    valid = [item for item in workspaces if item.get("valid")]
    if previous:
        selected = profile_by_name(workspaces, previous)
        if selected is None:
            raise DatabricksError("PROFILE_MISSING", f"selected profile '{previous}' no longer exists; Anvil will not switch workspaces automatically")
        if not selected["valid"]:
            raise DatabricksError("PROFILE_INVALID", f"selected profile '{previous}' is invalid; repair it with databricks auth login --profile {previous}")
        return selected
    if not valid:
        raise DatabricksError("NO_VALID_PROFILE", "no valid Databricks workspace profiles were found; authenticate with databricks auth login")
    if len(valid) == 1:
        return valid[0]
    if not sys.stdin.isatty():
        raise DatabricksError("PROFILE_SELECTION_REQUIRED", "multiple valid workspace profiles are available; rerun make databricks-setup in a terminal to choose one")
    print("Available Databricks workspace profiles:")
    for index, item in enumerate(valid, 1):
        print(f"  {index}. {item['name']}  {item['workspace_host']}")
    while True:
        answer = input("Choose the default profile number: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(valid):
            return valid[int(answer) - 1]
        print("Enter one of the listed profile numbers.")


def setup() -> dict[str, Any]:
    binary = cli_binary()
    if not binary:
        raise DatabricksError("CLI_MISSING", read_only_setup_message())
    version_text, version = cli_version()
    if version is None or version < MINIMUM_CLI:
        raise DatabricksError("CLI_TOO_OLD", f"Databricks CLI {version_text or 'unknown'} is unsupported; Anvil requires 1.0.0 or newer. Update it through the approved installation path. Anvil did not replace it.")
    prefs = load_preferences()
    profiles = discover_profiles()
    previous = prefs.get("selected_profile")
    if previous:
        prior = profile_by_name(profiles, str(previous))
        if prior is None or not prior.get("workspace") or not prior.get("valid"):
            if not sys.stdin.isatty():
                raise DatabricksError("PROFILE_INVALID", f"selected profile '{previous}' is invalid; run databricks auth login --profile {previous}, then retry")
            answer = input(f"Selected profile '{previous}' is invalid. Reauthenticate this same profile now? [y/N] ").strip().casefold()
            if answer not in {"y", "yes"}:
                raise DatabricksError("PROFILE_INVALID", "selected workspace is unchanged; authenticate it before using Databricks")
            result = subprocess.run([binary, "auth", "login", "--profile", str(previous)], timeout=900, check=False)
            if result.returncode != 0:
                raise DatabricksError("AUTHENTICATION_FAILED", "Databricks CLI login did not complete successfully")
            profiles = discover_profiles()
    if not any(item.get("workspace") and item.get("valid") for item in profiles):
        if not sys.stdin.isatty():
            raise DatabricksError("NO_VALID_PROFILE", "no valid Databricks workspace profile; run databricks auth login, then make databricks-setup")
        answer = input("No valid Databricks workspace profile is available. Start the official CLI login now? [y/N] ").strip().casefold()
        if answer not in {"y", "yes"}:
            raise DatabricksError("NO_VALID_PROFILE", "Databricks remains optional; authenticate with databricks auth login, then run make databricks-setup")
        result = subprocess.run([binary, "auth", "login"], timeout=900, check=False)
        if result.returncode != 0:
            raise DatabricksError("AUTHENTICATION_FAILED", "Databricks CLI login did not complete successfully")
        profiles = discover_profiles()
    selected = choose_profile(profiles, str(previous) if previous else None)
    host = validate_selected_profile(selected["name"], selected)
    path = save_preferences(selected["name"], host)
    return {"selected_profile": selected["name"], "workspace_host": host, "preferences_path": str(path), "credential_storage": "Databricks CLI only"}


def status() -> dict[str, Any]:
    binary = cli_binary()
    version_text, version = cli_version()
    value: dict[str, Any] = {
        "cli_installed": bool(binary),
        "cli_path": binary,
        "cli_version": version_text,
        "cli_supported": bool(version and version >= MINIMUM_CLI),
        "minimum_cli_version": "1.0.0",
        "profile_configured": False,
        "profile_valid": None,
        "selected_profile": None,
        "workspace_host": None,
        "identity_reachable": None,
        "running_all_purpose_compute": None,
        "running_sql_warehouses": None,
        "system_catalog_reachable": None,
        "system_schemas": [],
        "unavailable_system_schemas": [],
        "limitation": None,
    }
    if not binary:
        value["limitation"] = "Databricks CLI is not installed"
        return value
    if not value["cli_supported"]:
        value["limitation"] = "Databricks CLI is older than the supported minimum"
        return value
    try:
        prefs = load_preferences()
        selected = prefs.get("selected_profile")
        if not selected:
            value["limitation"] = "No Anvil default profile is selected; run make databricks-setup"
            return value
        value["selected_profile"] = selected
        value["profile_configured"] = True
        profiles = discover_profiles()
        listed = profile_by_name(profiles, str(selected))
        if not listed:
            value["profile_valid"] = False
            value["limitation"] = "Selected profile is missing; Anvil will not switch workspaces automatically"
            return value
        value["profile_valid"] = bool(listed.get("valid") and listed.get("workspace"))
        if not value["profile_valid"]:
            value["limitation"] = "Selected profile is invalid; repair its Databricks CLI authentication"
            return value
        try:
            host = validate_selected_profile(str(selected), listed)
        except DatabricksError:
            value["profile_valid"] = False
            value["identity_reachable"] = False
            raise
        value["workspace_host"] = host
        value["identity_reachable"] = True
        clusters_data = json_from_cli(["clusters", "list"], profile=str(selected), timeout=20)
        cluster_rows = [item for raw in item_list(clusters_data, "clusters") if (item := normalized_cluster(raw))]
        value["running_all_purpose_compute"] = sum(item["state"] == "RUNNING" for item in cluster_rows)
        warehouse_data = json_from_cli(["warehouses", "list"], profile=str(selected), timeout=20)
        warehouse_rows = [item for raw in item_list(warehouse_data, "warehouses", "endpoints") if (item := normalized_warehouse(raw))]
        value["running_sql_warehouses"] = sum(item["state"] == "RUNNING" for item in warehouse_rows)
        running_warehouses = [item for item in warehouse_rows if item["state"] == "RUNNING"]
        if len(running_warehouses) == 1:
            value["system_catalog_reachable"] = False
            catalog = execute_sql("SHOW SCHEMAS IN system", running_warehouses[0]["warehouse_id"], profile=str(selected), timeout=30)
            names = [str(row[0]) for row in catalog.get("rows", []) if isinstance(row, list) and row]
            key_schemas = {"access", "billing", "compute", "lakeflow", "query"}
            value["system_schemas"] = sorted(name for name in names if name in key_schemas)
            value["unavailable_system_schemas"] = sorted(key_schemas - set(value["system_schemas"]))
            value["system_catalog_reachable"] = True
        elif not running_warehouses:
            value["system_catalog_reachable"] = False
            value["limitation"] = "System catalog check needs a running SQL warehouse; Anvil did not start one"
        else:
            value["system_catalog_reachable"] = None
            value["limitation"] = "System catalog check needs a warehouse choice; Anvil did not select one silently"
    except DatabricksError as exc:
        value["limitation"] = str(exc)
        if exc.category.startswith("PROFILE") or exc.category.startswith("IDENTITY"):
            value["profile_valid"] = False
            value["identity_reachable"] = False
    return value


def status_text(value: dict[str, Any]) -> str:
    if not value["cli_installed"]:
        cli = "NO"
    elif value["cli_supported"]:
        cli = f"YES ({value['cli_version']})"
    else:
        cli = f"NO (found {value['cli_version']}; need >= 1.0.0)"
    profile = value["selected_profile"] or "not selected"
    if value["profile_valid"] is True:
        profile_state = "valid"
    elif value["profile_valid"] is False:
        profile_state = "invalid"
    else:
        profile_state = "not configured"
    def yes_no(item: Any) -> str:
        return "YES" if item is True else "NO" if item is False else "NOT CHECKED"
    lines = [
        "Databricks",
        f"  CLI installed          {cli}",
        f"  Auth profile           {profile} ({profile_state})",
        f"  Current identity       {yes_no(value['identity_reachable'])}",
        f"  Workspace host         {value['workspace_host'] or 'not available'}",
        f"  Running all-purpose    {value['running_all_purpose_compute'] if value['running_all_purpose_compute'] is not None else 'not checked'}",
        f"  Running SQL warehouses {value['running_sql_warehouses'] if value['running_sql_warehouses'] is not None else 'not checked'}",
        f"  System catalog         {yes_no(value['system_catalog_reachable'])}",
        f"  Key schemas            {', '.join(value['system_schemas']) if value['system_schemas'] else 'not checked'}",
        f"  Unavailable schemas    {', '.join(value['unavailable_system_schemas']) if value['system_catalog_reachable'] is True else 'not checked'}",
        f"  Setup                  make databricks-setup",
    ]
    if value.get("limitation"):
        lines.append(f"  Note                   {value['limitation']}")
    return "\n".join(lines)


def capabilities(value: dict[str, Any]) -> dict[str, Any]:
    ready = value["cli_supported"] and value["profile_valid"] is True
    return {
        "CLI": "YES" if value["cli_supported"] else "NO",
        "Auth profile": "YES" if value["profile_valid"] is True else "NO",
        "Remote Python": "YES" if ready and (value["running_all_purpose_compute"] or 0) > 0 else "NO",
        "SQL execution": "YES" if ready and (value["running_sql_warehouses"] or 0) > 0 else "NO",
        "System catalog": "YES" if value["system_catalog_reachable"] is True else "NO" if value["system_catalog_reachable"] is False else "UNKNOWN",
        "FinOps analysis": "YES" if value["system_catalog_reachable"] is True else "LIMITED" if ready else "NO",
        "Live schema discovery": "YES" if value["system_catalog_reachable"] is True else "NO",
    }


def render_approval_state(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--format", choices=("json", "text"), default="text")
    capabilities_parser = sub.add_parser("capabilities")
    capabilities_parser.add_argument("--format", choices=("json", "text"), default="text")
    sub.add_parser("setup")
    profiles_parser = sub.add_parser("profiles")
    profiles_parser.add_argument("--format", choices=("json", "text"), default="text")
    for name in ("clusters", "warehouses"):
        command = sub.add_parser(name)
        command.add_argument("--profile")
    python_parser = sub.add_parser("python")
    python_parser.add_argument("--cluster-id", required=True)
    python_parser.add_argument("--profile")
    python_parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    sql_parser = sub.add_parser("sql")
    sql_parser.add_argument("--warehouse-id", required=True)
    sql_parser.add_argument("--profile")
    sql_parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    sql_parser.add_argument("--parameters-json")
    sql_parser.add_argument("--allow-mutation", action="store_true", help="Use only after direct user approval for a write or configuration-changing statement")
    sql_parser.add_argument("statement", nargs="?")
    catalog_parser = sub.add_parser("system-catalog")
    catalog_parser.add_argument("--warehouse-id", required=True)
    catalog_parser.add_argument("--profile")
    catalog_parser.add_argument("--schema")
    args = parser.parse_args()
    try:
        if args.action == "setup":
            print(json.dumps(setup(), indent=2))
            return 0
        if args.action == "status":
            value = status()
            print(json.dumps(value, indent=2) if args.format == "json" else status_text(value))
            return 0
        if args.action == "capabilities":
            value = capabilities(status())
            if args.format == "json":
                print(json.dumps(value, indent=2))
            else:
                print("Databricks capabilities")
                for name, state in value.items():
                    print(f"  {name:<24} {state}")
            return 0
        if args.action == "profiles":
            profiles = discover_profiles()
            print(json.dumps(profiles, indent=2) if args.format == "json" else "\n".join(f"{p['name']}\t{p['workspace_host'] or 'account profile'}\t{'YES' if p['valid'] else 'NO'}" for p in profiles))
            return 0
        if args.action == "clusters":
            print(render_approval_state(discover_clusters(args.profile)))
            return 0
        if args.action == "warehouses":
            print(render_approval_state(discover_warehouses(args.profile)))
            return 0
        if args.action == "python":
            code = sys.stdin.read()
            print(render_approval_state(execute_python(code, args.cluster_id, args.profile, args.timeout)))
            return 0
        if args.action == "sql":
            statement = args.statement if args.statement is not None else sys.stdin.read()
            parameters = json.loads(args.parameters_json) if args.parameters_json else None
            result = execute_sql(statement, args.warehouse_id, args.profile, parameters, args.timeout, args.allow_mutation)
            print(render_approval_state(result))
            return 0
        selected, _, _ = resolve_profile(args.profile)
        if args.schema:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.schema):
                raise DatabricksError("SCHEMA_NAME_INVALID", "schema name must be a simple identifier")
            statement = f"SHOW TABLES IN system.{args.schema}"
        else:
            statement = "SHOW SCHEMAS IN system"
        print(render_approval_state(execute_sql(statement, args.warehouse_id, selected)))
        return 0
    except (DatabricksError, OSError, ValueError, json.JSONDecodeError) as exc:
        category = exc.category if isinstance(exc, DatabricksError) else "INVALID_INPUT"
        print(f"ERROR {category}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
