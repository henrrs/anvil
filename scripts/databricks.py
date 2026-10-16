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

SCRIPT_DIR = str(Path(__file__).resolve().parent)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from databricks_providers import discovery, resolver, state as provider_state  # noqa: E402
from databricks_providers import auth as auth_executor, auth_strategy, cli_install, owned_config, sdk, sql_connector as discovery_sql_connector  # noqa: E402
from databricks_providers import presentation, topology  # noqa: E402


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
    try:
        return provider_state.load_state()
    except ValueError as exc:
        raise DatabricksError("PREFERENCES_INVALID", "Anvil preferences contain a credential field; remove it and authenticate through the Databricks CLI")
    except OSError as exc:
        raise DatabricksError("PREFERENCES_INVALID", "Anvil Databricks preferences cannot be read") from exc


def save_preferences(profile: str, host: str, authentication: dict[str, Any] | None = None) -> Path:
    safe_host = workspace_host(host)
    if not re.fullmatch(r"anvil-[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?", profile):
        raise DatabricksError("PROFILE_OWNERSHIP_INVALID", "Anvil operations only use Anvil-owned anvil-* profiles")
    try:
        value = load_preferences()
    except DatabricksError as exc:
        if exc.category != "PREFERENCES_INVALID":
            raise
        value = {"schema_version": provider_state.SCHEMA_VERSION, "providers": {}, "capabilities": {}}
    environment = profile.removeprefix("anvil-")
    value.update({"selected_profile": profile, "workspace_host": safe_host,
                  "profile": {"name": profile, "ownership": "anvil",
                              "config_file": str(owned_config.config_file())},
                  "workspace": {"host": safe_host, "environment": environment},
                  "last_verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    if authentication:
        value["authentication"] = {key: authentication[key] for key in ("strategy", "provider", "cloud") if key in authentication}
    try:
        return provider_state.save_state(value)
    except ValueError as exc:
        raise DatabricksError("PREFERENCES_INVALID", "Anvil preferences contain a credential field") from exc


def workspace_host(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise DatabricksError("WORKSPACE_PROFILE_INVALID", "profile does not contain a safe HTTPS workspace URL")
    if parsed.hostname.casefold() in {"accounts.cloud.databricks.com", "accounts.azuredatabricks.net"}:
        raise DatabricksError("ACCOUNT_PROFILE_UNSUPPORTED", "account-level profiles cannot be used for workspace operations")
    return f"https://{parsed.netloc}"


def cli_binary() -> str | None:
    try:
        found = discovery.discover_cli(load_preferences())
    except DatabricksError:
        found = discovery.discover_cli({"providers": {}})
    return found.get("executable") if found.get("installed") else None


def cli_provider() -> dict[str, Any]:
    try:
        return discovery.discover_cli(load_preferences())
    except DatabricksError:
        return discovery.discover_cli({"providers": {}})


def sdk_provider() -> dict[str, Any]:
    try:
        return discovery.discover_sdk(load_preferences())
    except DatabricksError:
        return discovery.discover_sdk({"providers": {}})


def active_provider(capability: str) -> str | None:
    prefs = load_preferences()
    auth = prefs.get("authentication") if isinstance(prefs.get("authentication"), dict) else {}
    preferred = auth.get("provider") if auth.get("provider") in {"cli", "sdk"} else None
    allowed = None if not str(auth.get("strategy", "")).startswith("azure-cli") else {"cli", "sdk", "connect", "vscode"}
    sdk_state = sdk_provider()
    providers = {"cli": cli_provider(), "sdk": sdk_state,
                 "sql_connector": {"status": "NOT_INSTALLED"}, "connect": {"status": "NOT_INSTALLED"},
                 "vscode": {"status": "NOT_INSTALLED"}}
    if (capability in {"sql.execute", "system_tables.query"} and sdk_state.get("status") != "READY"
            and (allowed is None or "sql_connector" in allowed)):
        providers["sql_connector"] = discovery.discover_specialized(None)["sql_connector"]
    if capability == "python.execute" and providers["cli"].get("status") != "READY" and sdk_state.get("status") != "READY":
        providers["vscode"] = discovery._vscode()
    return resolver.resolve(providers, auth_valid=True, preferred_provider=preferred,
                            allowed_providers=allowed).get(capability, {}).get("provider")


def resolve_providers(providers: dict[str, dict[str, Any]], *, auth_valid: bool) -> dict[str, dict[str, Any]]:
    prefs = load_preferences()
    auth = prefs.get("authentication") if isinstance(prefs.get("authentication"), dict) else {}
    preferred = auth.get("provider") if auth.get("provider") in {"cli", "sdk"} else None
    allowed = None if not str(auth.get("strategy", "")).startswith("azure-cli") else {"cli", "sdk", "connect", "vscode"}
    return resolver.resolve(providers, auth_valid=auth_valid, preferred_provider=preferred,
                            allowed_providers=allowed)


def sdk_auth_options(profile: str | None) -> dict[str, str]:
    return {}


def parse_version(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"(?<!\d)v?(\d+)\.(\d+)\.(\d+)(?!\d)", value)
    return tuple(map(int, match.groups())) if match else None


def cli_version() -> tuple[str | None, tuple[int, int, int] | None]:
    provider = cli_provider()
    if not provider.get("installed"):
        return None, None
    raw = provider.get("version")
    version = parse_version(str(raw)) if raw else None
    return (".".join(map(str, version)) if version else str(raw or "unknown")), version


def require_cli() -> tuple[str, str]:
    provider = cli_provider()
    binary = provider.get("executable")
    if not provider.get("installed") or not binary:
        raise DatabricksError("CLI_MISSING", "Databricks CLI is not installed; see https://docs.databricks.com/aws/en/dev-tools/cli/install")
    version_text = provider.get("version")
    version = parse_version(str(version_text)) if version_text else None
    if version is None:
        raise DatabricksError("CLI_VERSION_UNKNOWN", "Databricks CLI version could not be identified")
    if version < MINIMUM_CLI:
        raise DatabricksError("CLI_TOO_OLD", f"Databricks CLI {version_text} is below Anvil's supported minimum 1.0.0")
    return binary, version_text or "unknown"


def run_cli(arguments: list[str], *, profile: str | None = None, timeout: float = 20,
            stdin: str | None = None, config_path: Path | None = None) -> str:
    binary, _ = require_cli()
    command = [binary, *arguments]
    if profile:
        command.extend(["--profile", profile])
    try:
        result = subprocess.run(command, input=stdin, capture_output=True, text=True, timeout=timeout, check=False,
                                env=owned_config.child_environment(profile=profile, path=config_path))
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


def discover_profiles(timeout: float = 60, *, config_path: Path | None = None) -> list[dict[str, Any]]:
    if cli_provider().get("status") == "READY":
        output = run_cli(["auth", "profiles"], timeout=timeout, config_path=config_path)
        profiles = parse_profiles(output)
    else:
        profiles = owned_config.read_profiles(config_path)
    profiles = [item for item in profiles if str(item.get("name", "")).startswith("anvil-")]
    for profile in profiles:
        try:
            profile["workspace_host"] = workspace_host(profile["host"])
            profile["workspace"] = True
        except DatabricksError:
            profile["workspace_host"] = None
            profile["workspace"] = False
            continue
        if cli_provider().get("status") != "READY":
            try:
                validate_selected_profile(profile["name"], profile, config_path=config_path)
                profile["valid"] = True
            except DatabricksError:
                profile["valid"] = False
    return profiles


def profile_by_name(profiles: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((item for item in profiles if item["name"] == name), None)


def validate_selected_profile(name: str, listed: dict[str, Any], *, config_path: Path | None = None) -> str:
    if not name.startswith("anvil-") or name == "__ANVIL_DEFAULT__":
        raise DatabricksError("PROFILE_OWNERSHIP_INVALID", "Anvil operations only use Anvil-owned anvil-* profiles")
    if not listed.get("workspace"):
        raise DatabricksError("WORKSPACE_PROFILE_INVALID", "selected profile is not a workspace profile")
    record = next((item for item in owned_config.read_profiles(config_path)
                   if item["name"].casefold() == name.casefold()), None)
    if not record or not record.get("host"):
        raise DatabricksError("PROFILE_MISSING", "selected Anvil-owned profile is missing from its managed configuration")
    try:
        configured_host = workspace_host(record["host"])
        listed_host = workspace_host(str(listed.get("workspace_host") or listed.get("host") or configured_host))
    except DatabricksError:
        raise
    if configured_host != listed_host:
        raise DatabricksError("PROFILE_CHANGED", "selected Anvil profile host changed; review make databricks-setup")
    failures: list[DatabricksError] = []
    if cli_provider().get("status") == "READY":
        try:
            described = run_cli(["auth", "describe"], profile=name, timeout=15, config_path=config_path)
            host_match = re.search(r"(?im)^\s*Host:\s*(https://[^\s]+)\s*$", described)
            if not host_match or workspace_host(host_match.group(1)) != configured_host:
                raise DatabricksError("PROFILE_INVALID", "Anvil profile did not validate its configured workspace host")
            identity = run_cli(["current-user", "me", "--output", "json"], profile=name,
                               timeout=20, config_path=config_path)
            identity_data = json.loads(identity)
            if isinstance(identity_data, dict) and (identity_data.get("userName") or identity_data.get("id")
                                                      or identity_data.get("applicationId")):
                return configured_host
            raise DatabricksError("IDENTITY_INVALID", "Databricks current-user response did not identify the active principal")
        except DatabricksError as exc:
            failures.append(exc)
        except (json.JSONDecodeError, ValueError):
            failures.append(DatabricksError("IDENTITY_INVALID", "Databricks identity response was invalid"))
    if sdk_provider().get("status") == "READY":
        try:
            response = sdk.call("identity", profile=name, timeout=20,
                                config_path=str(config_path) if config_path else None)
            host = workspace_host(str(response.get("host") or configured_host))
            identity = response.get("identity")
            if host == configured_host and isinstance(identity, dict) and (identity.get("userName")
                    or identity.get("id") or identity.get("applicationId")):
                return host
            raise DatabricksError("IDENTITY_INVALID", "Databricks current-user response did not validate the Anvil workspace profile")
        except RuntimeError as exc:
            failures.append(DatabricksError("IDENTITY_INVALID", "Anvil Unified Authentication could not validate the workspace identity"))
        except DatabricksError as exc:
            failures.append(exc)
    if failures:
        raise failures[-1]
    raise DatabricksError("AUTH_PROVIDER_UNAVAILABLE", "no supported Databricks provider is available to validate the Anvil profile")


def resolve_profile(explicit: str | None = None) -> tuple[str, str, list[dict[str, Any]]]:
    prefs = load_preferences()
    ownership = prefs.get("profile") if isinstance(prefs.get("profile"), dict) else {}
    if not explicit and (ownership.get("ownership") != "anvil"
                         or ownership.get("config_file") != str(owned_config.config_file())):
        raise DatabricksError("PROFILE_NOT_SELECTED", "no Anvil-owned Databricks profile is selected; run make databricks-setup")
    if explicit and (ownership.get("ownership") != "anvil"
                     or ownership.get("config_file") != str(owned_config.config_file())):
        raise DatabricksError("PROFILE_OWNERSHIP_INVALID", "Anvil commands only use profiles from Anvil's managed configuration")
    selected = explicit or ownership.get("name")
    if not selected:
        raise DatabricksError("PROFILE_NOT_SELECTED", "no Anvil Databricks profile is selected; run make databricks-setup")
    if not isinstance(selected, str) or not selected.startswith("anvil-"):
        raise DatabricksError("PROFILE_OWNERSHIP_INVALID", "Anvil operations only use Anvil-owned anvil-* profiles")
    profiles = discover_profiles()
    listed = profile_by_name(profiles, str(selected))
    if listed is None:
        raise DatabricksError("PROFILE_MISSING", "the selected Anvil-owned workspace profile is missing; rerun make databricks-setup")
    host = validate_selected_profile(str(selected), listed)
    return str(selected), host, profiles


def json_from_cli(arguments: list[str], *, profile: str, timeout: float = 20) -> Any:
    route: tuple[str, str, dict[str, Any]] | None = None
    if arguments[:2] == ["clusters", "list"]:
        route = ("compute.list", "clusters.list", {})
    elif arguments[:2] == ["clusters", "get"] and len(arguments) > 2:
        route = ("compute.get", "clusters.get", {"cluster_id": arguments[2]})
    elif arguments[:2] == ["warehouses", "list"]:
        route = ("warehouse.list", "warehouses.list", {})
    elif arguments[:2] == ["warehouses", "get"] and len(arguments) > 2:
        route = ("warehouse.get", "warehouses.get", {"warehouse_id": arguments[2]})
    elif arguments[:2] == ["jobs", "list"]:
        route = ("jobs.list", "jobs.list", {})
    elif arguments[:2] == ["jobs", "get"] and len(arguments) > 2:
        route = ("jobs.get", "jobs.get", {"job_id": arguments[2]})
    elif arguments[:2] == ["pipelines", "list"]:
        route = ("pipelines.list", "pipelines.list", {})
    elif arguments[:2] == ["pipelines", "get"] and len(arguments) > 2:
        route = ("pipelines.get", "pipelines.get", {"pipeline_id": arguments[2]})
    elif arguments[:2] == ["workspace", "list"]:
        path = arguments[2] if len(arguments) > 2 else "/"
        route = ("workspace.list", "workspace.list", {"path": path})
    if route and active_provider(route[0]) == "sdk":
        _capability, operation, payload = route
        try:
            return sdk.call(operation, profile=profile, timeout=int(timeout), **sdk_auth_options(profile), **payload)
        except RuntimeError as exc:
            raise DatabricksError("SDK_REQUEST_FAILED", f"Databricks SDK request failed for {operation}") from exc
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
    odbc = warehouse.get("odbc_params") if isinstance(warehouse.get("odbc_params"), dict) else {}
    return {
        "warehouse_id": identifier,
        "name": warehouse.get("name") or warehouse.get("warehouse_name"),
        "state": str(warehouse.get("state") or "UNKNOWN").upper(),
        "warehouse_type": warehouse.get("warehouse_type") or warehouse.get("type"),
        "size": warehouse.get("cluster_size") or warehouse.get("warehouse_size"),
        "min_clusters": warehouse.get("min_num_clusters") or warehouse.get("min_clusters"),
        "max_clusters": warehouse.get("max_num_clusters") or warehouse.get("max_clusters"),
        "auto_stop_minutes": warehouse.get("auto_stop_mins") or warehouse.get("auto_stop_minutes"),
        "http_path": odbc.get("path") or odbc.get("http_path") or warehouse.get("http_path"),
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
    selected, host, _ = resolve_profile(profile)
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
    selected_provider = active_provider("sql.execute")
    if selected_provider == "vscode":
        raise DatabricksError("CAPABILITY_ASSISTED", "SQL execution is not headless in VS Code; use the Databricks extension's supported SQL workflow")
    if selected_provider == "sql_connector":
        http_path = warehouse.get("http_path")
        if not http_path:
            raise DatabricksError("CAPABILITY_UNAVAILABLE", "SQL Connector was detected, but this warehouse did not expose a supported HTTP path")
        try:
            result = discovery_sql_connector.execute(profile=selected, host=host, http_path=http_path,
                                                     statement=statement, parameters=parameters, timeout=timeout)
        except RuntimeError as exc:
            category = "STATEMENT_TIMEOUT" if "timed out" in str(exc).casefold() else "SQL_CONNECTOR_FAILED"
            raise DatabricksError(category, "Databricks SQL Connector request failed or timed out") from exc
        if not isinstance(result.get("rows"), list):
            raise DatabricksError("API_RESPONSE_INVALID", "Databricks SQL Connector returned an invalid result")
        return bounded_result(result)
    if selected_provider == "sdk":
        try:
            response = sdk.call("sql.execute", profile=selected, timeout=timeout, **sdk_auth_options(selected), statement=statement,
                                warehouse_id=warehouse_id, parameters=parameters)
        except RuntimeError as exc:
            category = "STATEMENT_TIMEOUT" if "timed out" in str(exc).casefold() else "SDK_REQUEST_FAILED"
            raise DatabricksError(category, "Databricks SDK SQL request failed or timed out") from exc
        if not isinstance(response, dict):
            raise DatabricksError("API_RESPONSE_INVALID", "Databricks SDK returned an invalid SQL response")
        result = sql_result(response)
        if result["state"] != "SUCCEEDED":
            raise DatabricksError("STATEMENT_PENDING", "Databricks SDK returned before SQL execution completed")
        return result
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
    raw_state = response.get("status") or "UNKNOWN"
    if isinstance(raw_state, dict):
        raw_state = raw_state.get("state", "UNKNOWN")
    state = str(getattr(raw_state, "value", raw_state)).rsplit(".", 1)[-1].casefold()
    results = response.get("results") if isinstance(response.get("results"), dict) else {}
    if state in {"finished", "succeeded", "success"}:
        return bounded_result({"state": "Finished", "result_type": results.get("resultType", results.get("result_type")),
                               "data": results.get("data"), "truncated": bool(results.get("truncated"))})
    if state in {"error", "failed", "canceled", "cancelled"}:
        raise DatabricksError("COMMAND_" + state.upper(), f"Databricks Python command ended with state {state}")
    if state not in {"queued", "running", "pending"}:
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
    selected_provider = active_provider("python.execute")
    if selected_provider == "vscode":
        raise DatabricksError("CAPABILITY_ASSISTED", "Python execution is available as an assisted VS Code workflow; Anvil cannot automate the IDE")
    if selected_provider == "sdk":
        try:
            response = sdk.call("python.execute", profile=selected, timeout=timeout, **sdk_auth_options(selected),
                                cluster_id=cluster_id, code=code)
        except RuntimeError as exc:
            category = "COMMAND_TIMEOUT" if "timed out" in str(exc).casefold() else "SDK_REQUEST_FAILED"
            raise DatabricksError(category, "Databricks SDK Python execution failed or timed out") from exc
        normalized = command_result(response) if isinstance(response, dict) else None
        if normalized is None:
            raise DatabricksError("COMMAND_RESULT_INVALID", "Databricks SDK returned an invalid Python result")
        return normalized
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
    return "CLI installation is attempted only by make databricks-setup; Anvil installs to its private user-local data directory and never elevates privileges."


def provider_snapshot() -> dict[str, dict[str, Any]]:
    state = load_preferences()
    cli = discovery.discover_cli(state)
    cached_cli = state.get("providers", {}).get("cli", {}) if isinstance(state.get("providers"), dict) else {}
    if isinstance(cached_cli, dict) and cached_cli.get("status") == "BLOCKED" and cached_cli.get("failure"):
        cli["setup_failure"] = cached_cli.get("failure")
    if cli.get("status") == "NOT_INSTALLED" and isinstance(cached_cli, dict) and cached_cli.get("status") == "BLOCKED":
        cli.update({"status": "BLOCKED", "failure": cached_cli.get("failure"), "message": cached_cli.get("message")})
    sdk_state = discovery.discover_sdk(state)
    cached_sdk = state.get("providers", {}).get("sdk", {}) if isinstance(state.get("providers"), dict) else {}
    if sdk_state.get("status") == "NOT_INSTALLED" and isinstance(cached_sdk, dict) and cached_sdk.get("status") == "BLOCKED":
        sdk_state.update({"status": "BLOCKED", "failure": cached_sdk.get("failure"), "message": cached_sdk.get("message")})
    specialized = discovery.discover_specialized(sdk_state.get("python"))
    return {"cli": cli, "sdk": sdk_state, **specialized}


def _profile_metadata(prefs: dict[str, Any]) -> dict[str, Any]:
    value = prefs.get("profile")
    if (not isinstance(value, dict) or value.get("ownership") != "anvil"
            or value.get("config_file") != str(owned_config.config_file())
            or not isinstance(value.get("name"), str)
            or not value["name"].startswith("anvil-")):
        return {}
    return value


def _external_profiles() -> list[dict[str, Any]]:
    path = owned_config.external_config_file()
    try:
        if path.resolve() == owned_config.config_file().resolve():
            return []
    except OSError:
        pass
    return discovery.config_profiles(path)


def _profile_name(environment: str) -> str:
    return f"anvil-{environment}"


def _normalize_environment(value: str) -> str:
    raw = re.sub(r"\s+", "-", value.strip().casefold()).strip("-")
    aliases = {"development": "dev", "develop": "dev", "dev": "dev",
               "staging": "staging", "stage": "staging",
               "production": "prod", "prod": "prod", "production-ready": "prod"}
    label = aliases.get(raw, raw)
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?", label):
        raise DatabricksError("ENVIRONMENT_INVALID", "use a short neutral environment label such as dev, staging, or prod")
    return label


def _collect_workspace(prefs: dict[str, Any], profile_meta: dict[str, Any]) -> tuple[str, str]:
    if not sys.stdin.isatty():
        raise DatabricksError("WORKSPACE_REQUIRED", "workspace URL and environment must be collected in an interactive terminal")
    workspace_meta = prefs.get("workspace") if isinstance(prefs.get("workspace"), dict) else {}
    suggestion = os.environ.get("ANVIL_DATABRICKS_HOST") or workspace_meta.get("host") or prefs.get("workspace_host")
    if suggestion:
        try:
            suggestion = workspace_host(str(suggestion))
        except DatabricksError:
            suggestion = None
    host = ""
    if suggestion:
        print(f"Previously recorded workspace: {suggestion}")
        answer = input("Use this workspace? [Y/n]: ").strip().casefold()
        if answer not in {"n", "no"}:
            host = str(suggestion)
    while not host:
        candidate = input("Workspace URL: ").strip()
        try:
            host = workspace_host(candidate)
        except DatabricksError:
            print("Enter a workspace URL beginning with https://.")
    default_environment = str(workspace_meta.get("environment") or
                              profile_meta.get("name", "anvil-dev").removeprefix("anvil-") or "dev")
    try:
        default_environment = _normalize_environment(default_environment)
    except DatabricksError:
        default_environment = "dev"
    default_choice = {"dev": "1", "staging": "2", "prod": "3"}.get(default_environment, "4")
    print("Environment")
    print("  [1] development")
    print("  [2] staging")
    print("  [3] production")
    print("  [4] custom")
    choice = input(f"Selection [{default_choice}]: ").strip().casefold() or default_choice
    labels = {"1": "dev", "2": "staging", "3": "prod",
              "development": "dev", "dev": "dev", "staging": "staging",
              "production": "prod", "prod": "prod"}
    if choice in labels:
        environment = labels[choice]
    elif choice in {"4", "custom"}:
        custom = input("Environment label: ").strip()
        environment = _normalize_environment(custom)
    else:
        environment = _normalize_environment(choice)
    return host, environment


def _setup_plan(providers: dict[str, dict[str, Any]], *, reset: bool = False) -> dict[str, Any]:
    prefs = load_preferences()
    profile_meta = _profile_metadata(prefs)
    workspace_meta = prefs.get("workspace") if isinstance(prefs.get("workspace"), dict) else {}
    existing = owned_config.read_profiles()
    selected = profile_meta.get("name")
    environment = str(workspace_meta.get("environment") or (selected or "anvil-dev").removeprefix("anvil-"))
    try:
        environment = _normalize_environment(environment)
    except DatabricksError:
        environment = "dev"
    profile = _profile_name(environment)
    target_record = next((item for item in existing if item["name"].casefold() == profile.casefold()), None)
    host = workspace_meta.get("host") or prefs.get("workspace_host")
    cloud = topology.workspace_cloud(str(host or ""))
    environment_info = topology.detect_topology(tty=sys.stdin.isatty())
    cli = providers["cli"]
    sdk_state = providers["sdk"]
    auth_plan = auth_strategy.resolve(topology=environment_info, cloud=cloud,
        cli_ready=cli.get("status") == "READY" or not cli.get("installed"),
        sdk_ready=sdk_state.get("status") == "READY",
        azure_cli_available=bool(shutil.which("az")), azure_cli_authenticated=False,
        anvil_profile_valid=False)
    external = _external_profiles()
    auth_plan["session_check"] = "not checked in dry-run"
    actions = []
    if reset:
        actions.append("back up and replace only the Anvil-owned Databricks config")
    elif target_record and target_record.get("host") == (host or target_record.get("host")):
        actions.append("revalidate the selected Anvil-owned profile")
    elif target_record:
        actions.append(f"resolve the existing Anvil profile name collision for {profile}")
    else:
        actions.append(f"create Anvil-owned profile {profile}")
    actions += ["authenticate using the workspace cloud and detected topology",
                "validate current user and workspace access",
                "atomically activate the Anvil config and save non-secret metadata"]
    return {
        "dry_run": True, "reset": reset,
        "workspace_host": host, "environment": environment, "profile": profile,
        "profile_created": not bool(target_record and target_record.get("host") == (host or target_record.get("host"))),
        "ownership": "Anvil", "config_file": str(owned_config.config_file()),
        "external_profiles_detected": len(external), "external_profiles_used": False,
        "environment_conflicts": owned_config.environment_conflicts(),
        "providers": providers, "topology": environment_info,
        "cloud": cloud, "authentication": auth_plan,
        "would_backup_config": str(owned_config.config_file()) if reset and owned_config.config_file().exists() else None,
        "plan": actions, "changes_performed": False,
    }


def _save_provider_snapshot(providers: dict[str, dict[str, Any]], install_result: dict[str, Any] | None = None,
                            sdk_install_result: dict[str, Any] | None = None) -> None:
    state = load_preferences()
    records = state.setdefault("providers", {})
    cli = providers["cli"]
    if install_result and install_result.get("status") != "READY":
        records["cli"] = {"status": "BLOCKED", "failure": install_result.get("failure", "unknown"),
                          "message": install_result.get("message"), "installed": cli.get("installed", False),
                          "executable": cli.get("executable")}
    elif cli.get("status") == "READY" or cli.get("installed"):
        records["cli"] = {key: cli.get(key) for key in ("status", "executable", "version", "discovered_by", "path_visible", "absolute_usable")}
    sdk_state = providers["sdk"]
    if sdk_state.get("status") == "READY":
        records["sdk"] = {"status": "READY", "python": sdk_state.get("python"), "version": sdk_state.get("version"),
                           "environment": sdk_state.get("environment"), "isolated": sdk_state.get("isolated")}
    elif sdk_install_result:
        records["sdk"] = {"status": "BLOCKED", "failure": sdk_install_result.get("failure")}
    records["vscode"] = {"status": providers["vscode"].get("status"),
                          "extension_id": providers["vscode"].get("extension_id", discovery.OFFICIAL_VSCODE_EXTENSION)}
    records["connect"] = providers["connect"]
    records["sql_connector"] = providers["sql_connector"]
    provider_state.save_state(state)


def _setup_summary(providers: dict[str, dict[str, Any]], auth_valid: bool, selected: str | None) -> dict[str, Any]:
    capability_map = resolve_providers(providers, auth_valid=auth_valid)
    health = resolver.overall_state(providers, capability_map, auth_valid=auth_valid)
    return {"overall": health, "selected_profile": selected,
            "external_profiles_detected": len(_external_profiles()), "external_profiles_used": False,
            "providers": providers, "capabilities": capability_map}


def _candidate_identity(profile: str, host: str, config_path: Path) -> tuple[str, str]:
    listed = {"name": profile, "host": host, "workspace_host": host,
              "workspace": True, "valid": True}
    validated_host = validate_selected_profile(profile, listed, config_path=config_path)
    provider = "cli" if cli_provider().get("status") == "READY" else "sdk"
    if provider == "cli" and sdk_provider().get("status") == "READY":
        # Validation may have reached SDK fallback when CLI auth was unusable.
        try:
            run_cli(["current-user", "me", "--output", "json"], profile=profile,
                    timeout=5, config_path=config_path)
        except DatabricksError:
            provider = "sdk"
    return validated_host, provider


def _authentication_context(host: str, providers: dict[str, dict[str, Any]], *,
                            azure_authenticated: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    environment = topology.detect_topology(tty=sys.stdin.isatty())
    cloud = topology.workspace_cloud(host)
    decision = auth_strategy.resolve(
        topology=environment, cloud=cloud,
        cli_ready=providers.get("cli", {}).get("status") == "READY",
        sdk_ready=providers.get("sdk", {}).get("status") == "READY",
        azure_cli_available=bool(shutil.which("az")),
        azure_cli_authenticated=azure_authenticated,
        anvil_profile_valid=False)
    return environment, decision


def _authenticate_workspace(host: str, profile: str, config_path: Path,
                            providers: dict[str, dict[str, Any]], decision: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, str | None]:
    cloud = topology.workspace_cloud(host)
    strategy = str(decision.get("strategy"))
    config_record = next((item for item in owned_config.read_profiles(config_path)
                          if item["name"].casefold() == profile.casefold()), None)
    if not config_record:
        return None, None, "PROFILE_CREATE_FAILED"
    if strategy.startswith("azure-cli"):
        try:
            owned_config.set_profile_auth_type(config_path, profile, "azure-cli")
        except (OSError, ValueError):
            return None, None, "PROFILE_CREATE_FAILED"

    try:
        validated_host, provider = _candidate_identity(profile, host, config_path)
        auth_method = "azure-cli-session" if cloud == "azure" and strategy.startswith("azure-cli") else "unified-auth"
        if config_record.get("auth_type") == "databricks-cli" or strategy == "databricks-cli-u2m":
            auth_method = "databricks-cli-u2m"
        return {"strategy": auth_method, "provider": provider, "cloud": cloud}, validated_host, None
    except DatabricksError as exc:
        if strategy == "azure-cli-session":
            return None, None, "IDENTITY_INVALID"

    if strategy == "azure-cli-device-code":
        result = auth_executor.run_azure_device_login()
        auth_method = "azure-cli-device-code"
    elif strategy == "azure-cli-interactive":
        result = auth_executor.run_azure_interactive_login()
        auth_method = "azure-cli-interactive"
    elif strategy == "databricks-cli-u2m":
        binary = providers.get("cli", {}).get("executable")
        if not binary:
            return None, None, "AUTH_PROVIDER_UNAVAILABLE"
        result = auth_executor.run_databricks_login(str(binary), host, profile,
                                                    config_path=str(config_path))
        auth_method = "databricks-cli-u2m"
    else:
        return None, None, "AUTH_REQUIRED"
    if result.get("status") != "READY":
        return None, None, str(result.get("category") or "AUTH_FAILED")
    if owned_config.plaintext_credential_fields(config_path):
        return None, None, "PLAINTEXT_AUTH_STORAGE_UNSAFE"
    try:
        validated_host, provider = _candidate_identity(profile, host, config_path)
    except DatabricksError:
        return None, None, "PROFILE_VALIDATION_FAILED"
    return {"strategy": auth_method, "provider": provider, "cloud": cloud}, validated_host, None


def setup(dry_run: bool = False, *, reset: bool = False) -> dict[str, Any]:
    prefs = load_preferences()
    profile_meta = _profile_metadata(prefs)
    target = owned_config.config_file()
    if target.exists() and not profile_meta and not dry_run:
        raise DatabricksError("CONFIG_OWNERSHIP_AMBIGUOUS", "Anvil's config path already contains unowned data; it was left unchanged")
    if dry_run:
        plan = _setup_plan(provider_snapshot(), reset=reset)
        if target.exists() and not profile_meta:
            plan["config_ownership_issue"] = "ambiguous"
            plan["plan"] = ["inspect the existing Anvil config without modifying it"]
        elif target.exists() and not owned_config.valid_config(target):
            plan["config_ownership_issue"] = "invalid"
            plan["plan"] = ["review or reset the invalid Anvil-owned config"]
        return plan

    providers = provider_snapshot()
    if profile_meta and target.is_file() and not reset and not owned_config.valid_config(target):
        raise DatabricksError("CONFIG_INVALID", "Anvil's managed Databricks config is malformed; it was left unchanged")
    if profile_meta and target.is_file() and not reset:
        name = str(profile_meta["name"])
        owned_record = next((item for item in owned_config.read_profiles()
                             if item["name"].casefold() == name.casefold()), None)
        if owned_record and owned_record.get("host"):
            try:
                safe_host = workspace_host(owned_record["host"])
                host, _ = _candidate_identity(name, safe_host, target)
                summary = _setup_summary(providers, True, name)
                summary.update({"dry_run": False, "already_configured": True, "profile_created": False,
                                "profile": name,
                                "workspace_host": host, "environment": str((prefs.get("workspace") or {}).get("environment", "dev")),
                                "ownership": "Anvil", "cloud": topology.workspace_cloud(host),
                                "authentication": prefs.get("authentication") or {},
                                "topology": topology.detect_topology(tty=sys.stdin.isatty()),
                                "environment_conflicts": owned_config.environment_conflicts(),
                                "credential_storage": "official Databricks/Azure authentication storage; Anvil stores metadata only"})
                return summary
            except DatabricksError:
                pass

    if not sys.stdin.isatty():
        return {"overall": "NOT_CONFIGURED", "dry_run": False, "providers": providers,
                "authentication": {}, "topology": topology.detect_topology(tty=False),
                "auth_error": "WORKSPACE_REQUIRED",
                "next_step": "Run make databricks-setup in an interactive terminal to enter the workspace URL and environment.",
                "external_profiles_detected": len(_external_profiles()), "external_profiles_used": False}

    try:
        host, environment = _collect_workspace(prefs, profile_meta)
    except KeyboardInterrupt:
        return {"overall": "NOT_CONFIGURED", "dry_run": False, "providers": providers,
                "selected_profile": None, "auth_error": "AUTH_CANCELLED",
                "next_step": "Rerun make databricks-setup when ready.",
                "external_profiles_detected": len(_external_profiles()), "external_profiles_used": False,
                "authentication": {}, "topology": topology.detect_topology(tty=True)}
    profile = _profile_name(environment)
    if target.exists() and not profile_meta:
        raise DatabricksError("CONFIG_OWNERSHIP_AMBIGUOUS", "Anvil's config path contains data without ownership metadata; use a different Anvil config location")
    try:
        continue_setup = input(f"Anvil will create {profile} in its managed config. Existing Databricks profiles will not be changed. Continue? [Y/n]: ").strip().casefold() in {"", "y", "yes"}
    except KeyboardInterrupt:
        continue_setup = False
    if not continue_setup:
        return {"overall": "NOT_CONFIGURED", "dry_run": False, "providers": providers,
                "selected_profile": None, "auth_error": "AUTH_CANCELLED",
                "next_step": "Rerun make databricks-setup when ready.", "external_profiles_detected": len(_external_profiles()),
                "external_profiles_used": False, "authentication": {},
                "topology": topology.detect_topology(tty=True)}

    install_result = None
    sdk_install_result = None
    if providers["cli"].get("status") != "READY":
        install_result = cli_install.attempt_cli_install()
        providers = provider_snapshot()
        if providers["cli"].get("status") != "READY" and providers["sdk"].get("status") != "READY":
            sdk_install_result = cli_install.install_sdk()
            providers = provider_snapshot()
            if sdk_install_result.get("status") != "READY":
                providers["sdk"] = {"status": "BLOCKED", "failure": sdk_install_result.get("failure", "unknown"),
                                    "message": sdk_install_result.get("message")}
    _save_provider_snapshot(providers, install_result, sdk_install_result)
    if providers["cli"].get("status") != "READY" and providers["sdk"].get("status") != "READY":
        return {"overall": "BLOCKED", "dry_run": False, "providers": providers,
                "auth_error": "AUTH_PROVIDER_UNAVAILABLE", "selected_profile": None,
                "authentication": {}, "topology": topology.detect_topology(tty=True),
                "next_step": "Install or allow one supported Databricks provider, then rerun make databricks-setup."}

    base_path = target
    if reset:
        base_path = target.with_name(f".anvil-reset-empty-{os.getpid()}")
    profile_preexisting = any(item["name"].casefold() == profile.casefold()
                              for item in owned_config.read_profiles(base_path))
    old_state = dict(prefs)
    state_existed = provider_state.state_path().exists()
    backup: Path | None = None
    try:
        stage = owned_config.stage_profile(profile, host, base_path=base_path)
    except FileExistsError:
        raise DatabricksError("PROFILE_COLLISION", "this Anvil profile name already belongs to another workspace; choose a different environment or use RESET=1")
    except (OSError, ValueError) as exc:
        raise DatabricksError("PROFILE_CREATE_FAILED", "Anvil could not stage a private workspace profile") from exc
    if owned_config.plaintext_credential_fields(stage):
        owned_config.discard_stage(stage)
        raise DatabricksError("PLAINTEXT_AUTH_STORAGE_UNSAFE", "Anvil will not use a config file containing plaintext credential fields")

    _, azure_authenticated = auth_executor.azure_cli_status() if topology.workspace_cloud(host) == "azure" else (False, False)
    environment_info, decision = _authentication_context(host, providers, azure_authenticated=azure_authenticated)
    print(f"\nWorkspace: {host}\nEnvironment: {environment_info['kind']}\nCloud: {topology.workspace_cloud(host)}")
    print(f"Profile: {profile} (Anvil-managed)\nAuthentication: {str(decision['strategy']).replace('-', ' ')}")
    conflicts = owned_config.environment_conflicts()
    if conflicts:
        print("External Databricks environment variables will be isolated: " + ", ".join(conflicts))
    try:
        continue_auth = input("Continue with this authentication method? [Y/n]: ").strip().casefold() in {"", "y", "yes"}
    except KeyboardInterrupt:
        owned_config.discard_stage(stage)
        return {"overall": "NOT_CONFIGURED", "dry_run": False, "providers": providers,
                "selected_profile": None, "auth_error": "AUTH_CANCELLED",
                "next_step": "Rerun make databricks-setup when ready.", "external_profiles_detected": len(_external_profiles()),
                "external_profiles_used": False, "authentication": decision, "topology": environment_info}
    if not continue_auth:
        owned_config.discard_stage(stage)
        return {"overall": "NOT_CONFIGURED", "dry_run": False, "providers": providers,
                "selected_profile": None, "auth_error": "AUTH_CANCELLED",
                "next_step": "Rerun make databricks-setup when ready.", "external_profiles_detected": len(_external_profiles()),
                "external_profiles_used": False, "authentication": decision, "topology": environment_info}

    try:
        authentication, validated_host, auth_error = _authenticate_workspace(host, profile, stage, providers, decision)
        if not authentication or not validated_host or auth_error:
            owned_config.discard_stage(stage)
            summary = _setup_summary(providers, False, None)
            summary.update({"dry_run": False, "workspace_host": host, "environment": environment,
                           "profile": profile, "ownership": "Anvil", "auth_error": auth_error or "AUTH_FAILED",
                           "authentication": decision, "topology": environment_info,
                           "environment_conflicts": conflicts,
                           "next_step": "Resolve the authentication issue and rerun make databricks-setup."})
            return summary
        backup = owned_config.backup_existing(reset=reset)
        owned_config.commit_staged(stage)
        try:
            path = save_preferences(profile, validated_host, authentication)
            state = load_preferences()
            summary = _setup_summary(providers, True, profile)
            state["capabilities"] = summary["capabilities"]
            provider_state.save_state(state)
        except BaseException:
            owned_config.restore_backup(backup)
            if state_existed:
                provider_state.save_state(old_state)
            else:
                provider_state.state_path().unlink(missing_ok=True)
            raise
    except DatabricksError:
        owned_config.discard_stage(stage)
        raise
    except OSError as exc:
        owned_config.discard_stage(stage)
        raise DatabricksError("PROFILE_CREATE_FAILED", "Anvil could not safely activate its validated profile") from exc
    except BaseException:
        owned_config.discard_stage(stage)
        raise

    summary.update({"dry_run": False, "profile_created": not profile_preexisting,
                    "already_configured": False, "workspace_host": validated_host,
                    "environment": environment, "ownership": "Anvil", "config_file": str(path),
                    "configuration_backup": str(backup) if backup else None,
                    "authentication": authentication, "topology": environment_info,
                    "environment_conflicts": conflicts,
                    "credential_storage": "official Databricks/Azure authentication storage; Anvil stores metadata only",
                    "auth_error": None,
                    "next_step": None if summary["overall"] in {"READY", "DEGRADED"} else "Check provider availability and rerun make databricks-setup."})
    return summary


def status() -> dict[str, Any]:
    providers = provider_snapshot()
    cli = providers["cli"]
    sdk_state = providers["sdk"]
    binary = cli.get("executable")
    version_text = cli.get("version")
    version = parse_version(str(version_text)) if version_text else None
    cli_ready = cli.get("status") == "READY"
    cli_failure = cli.get("failure")
    if not cli_failure and cli.get("status") == "UNSUPPORTED_VERSION":
        cli_failure = "unsupported-version"
    elif not cli_failure and cli.get("status") == "BROKEN":
        cli_failure = "binary-invalid"
    elif not cli_failure and cli_ready and not cli.get("path_visible"):
        cli_failure = "path-misconfigured"
    value: dict[str, Any] = {
        "cli_installed": bool(cli.get("installed")),
        "cli_path": binary,
        "cli_version": version_text,
        "cli_supported": cli_ready,
        "cli_path_visible": cli.get("path_visible", False),
        "cli_failure": cli_failure,
        "cli_setup_failure": cli.get("setup_failure"),
        "cli_provider_status": cli.get("status"),
        "cli_absolute_usable": cli.get("absolute_usable", False),
        "sdk_installed": sdk_state.get("status") == "READY",
        "sdk_python": sdk_state.get("python"),
        "sdk_version": sdk_state.get("version"),
        "sdk_isolated": sdk_state.get("isolated", False),
        "vscode": providers["vscode"],
        "connect": providers["connect"],
        "sql_connector": providers["sql_connector"],
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
    prefs = load_preferences()
    profile_meta = _profile_metadata(prefs)
    selected = profile_meta.get("name")
    value.update({"selected_profile": selected,
                  "profile_configured": bool(selected and owned_config.config_file().is_file()),
                  "workspace_host": (prefs.get("workspace") or {}).get("host") if isinstance(prefs.get("workspace"), dict) else None,
                  "profile_ownership": "Anvil" if selected else None,
                  "authentication_strategy": (prefs.get("authentication") or {}).get("strategy") if isinstance(prefs.get("authentication"), dict) else None,
                  "external_profiles_detected": len(_external_profiles()), "external_profiles_used": False,
                  "environment_conflicts": owned_config.environment_conflicts()})
    usable_provider = cli_ready or sdk_state.get("status") == "READY"
    if not usable_provider:
        if cli.get("status") == "BLOCKED":
            value["limitation"] = "CLI setup is blocked: " + str(cli.get("failure"))
        elif not cli.get("installed") and sdk_state.get("status") != "READY":
            value["limitation"] = "Databricks CLI is not installed"
        else:
            value["limitation"] = "No supported headless Databricks provider is installed"
        cap_map = resolve_providers(providers, auth_valid=False)
        value["resolved_capabilities"] = cap_map
        value["overall"] = resolver.overall_state(providers, cap_map, auth_valid=False)
        return value
    try:
        if not selected:
            value["limitation"] = "No Anvil-owned Databricks profile is configured; external profiles are not used. Run make databricks-setup."
            cap_map = resolve_providers(providers, auth_valid=False)
            value["resolved_capabilities"] = cap_map
            value["overall"] = resolver.overall_state(providers, cap_map, auth_valid=False)
            return value
        profiles = discover_profiles()
        listed = profile_by_name(profiles, str(selected))
        if not listed:
            value["profile_valid"] = False
            value["limitation"] = "The Anvil-owned profile is missing; run make databricks-setup to recreate it."
            cap_map = resolve_providers(providers, auth_valid=False)
            value["resolved_capabilities"] = cap_map
            value["overall"] = resolver.overall_state(providers, cap_map, auth_valid=False)
            return value
        value["profile_valid"] = bool(listed.get("valid") and listed.get("workspace"))
        host = validate_selected_profile(str(selected), listed)
        value["profile_valid"] = True
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
    auth_valid = value["profile_valid"] is True and value["identity_reachable"] is True
    cap_map = resolve_providers(providers, auth_valid=auth_valid)
    value["resolved_capabilities"] = cap_map
    value["overall"] = resolver.overall_state(providers, cap_map, auth_valid=auth_valid)
    return value


def local_status() -> dict[str, Any]:
    """Return installed providers and saved preferences without workspace calls."""
    providers = provider_snapshot()
    prefs = load_preferences()
    profile_meta = _profile_metadata(prefs)
    selected = profile_meta.get("name")
    workspace_meta = prefs.get("workspace") if isinstance(prefs.get("workspace"), dict) else {}
    value: dict[str, Any] = {
        "cli_installed": bool(providers["cli"].get("installed")),
        "cli_path": providers["cli"].get("executable"),
        "cli_version": providers["cli"].get("version"),
        "cli_supported": providers["cli"].get("status") == "READY",
        "cli_path_visible": providers["cli"].get("path_visible", False),
        "cli_failure": providers["cli"].get("failure"),
        "cli_setup_failure": providers["cli"].get("setup_failure"),
        "cli_provider_status": providers["cli"].get("status"),
        "cli_absolute_usable": providers["cli"].get("absolute_usable", False),
        "sdk_installed": providers["sdk"].get("status") == "READY",
        "sdk_python": providers["sdk"].get("python"),
        "sdk_version": providers["sdk"].get("version"),
        "sdk_isolated": providers["sdk"].get("isolated", False),
        "vscode": providers["vscode"], "connect": providers["connect"],
        "sql_connector": providers["sql_connector"],
        "minimum_cli_version": "1.0.0",
        "profile_configured": bool(selected and owned_config.config_file().is_file()), "profile_valid": None,
        "selected_profile": selected, "workspace_host": workspace_meta.get("host"),
        "profile_ownership": "Anvil" if selected else None,
        "authentication_strategy": (prefs.get("authentication") or {}).get("strategy") if isinstance(prefs.get("authentication"), dict) else None,
        "external_profiles_detected": len(_external_profiles()), "external_profiles_used": False,
        "environment_conflicts": owned_config.environment_conflicts(),
        "identity_reachable": None, "running_all_purpose_compute": None,
        "running_sql_warehouses": None, "system_catalog_reachable": None,
        "system_schemas": [], "unavailable_system_schemas": [],
        "limitation": "Local provider inventory only; authentication and workspace were not checked",
        "auth_checked": False, "workspace_checked": False,
    }
    cap_map = resolver.resolve_local(providers)
    value["resolved_capabilities"] = cap_map
    value["overall"] = "NOT_CHECKED"
    return value


def status_text(value: dict[str, Any], *, verbose: bool = False) -> str:
    return presentation.doctor_text(value, verbose=verbose)


def capabilities(value: dict[str, Any]) -> dict[str, Any]:
    cap_map = value.get("resolved_capabilities", {})
    def selected(capability: str) -> str:
        item = cap_map.get(capability, {})
        provider = item.get("provider")
        return resolver.PROVIDER_LABELS.get(provider, provider) if provider else item.get("state", "UNAVAILABLE")
    auth = ("NOT_CHECKED" if value.get("auth_checked") is False else
            "READY" if value.get("profile_valid") is True else "NOT_CONFIGURED")
    sql_available = selected("sql.execute") not in {"UNAVAILABLE", "ASSISTED"}
    system = "YES" if value.get("system_catalog_reachable") is True else "NO" if value.get("system_catalog_reachable") is False else "UNKNOWN"
    return {
        "Authentication": auth,
        "Authentication strategy": value.get("authentication_strategy") or "NOT_CONFIGURED",
        "Anvil profile": value.get("selected_profile") or "NOT_CONFIGURED",
        "Workspace API": selected("workspace.list"),
        "Cluster discovery": selected("compute.list"),
        "Warehouse discovery": selected("warehouse.list"),
        "Remote Python": selected("python.execute"),
        "SQL": selected("sql.execute"),
        "System tables": selected("system_tables.query") if system != "NO" else "NO",
        "FinOps": selected("system_tables.query") if sql_available and value.get("system_catalog_reachable") is True else "LIMITED" if sql_available else "UNAVAILABLE",
        "Spark development": selected("spark.develop"),
        "Bundles": selected("bundles.run"),
        "CLI": "READY" if value.get("cli_supported") else "UNSUPPORTED VERSION" if value.get("cli_provider_status") == "UNSUPPORTED_VERSION" else "BLOCKED" if value.get("cli_failure") else "NOT INSTALLED",
        "SDK": "READY" if value.get("sdk_installed") else "NOT INSTALLED",
        "VS Code extension": value.get("vscode", {}).get("extension", "UNKNOWN"),
        "Databricks Connect": "READY" if value.get("connect", {}).get("status") == "READY" else "NOT CONFIGURED",
        "Overall": value.get("overall", "NOT_CONFIGURED"),
    }


def render_approval_state(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--format", choices=("json", "text"), default="text")
    status_parser.add_argument("--local", action="store_true", help="Inspect local providers and saved preferences without contacting Databricks")
    status_parser.add_argument("--verbose", action="store_true")
    capabilities_parser = sub.add_parser("capabilities")
    capabilities_parser.add_argument("--format", choices=("json", "text"), default="text")
    capabilities_parser.add_argument("--verbose", action="store_true")
    sub.add_parser("setup")
    sub.choices["setup"].add_argument("--dry-run", action="store_true")
    sub.choices["setup"].add_argument("--reset", action="store_true")
    sub.choices["setup"].add_argument("--format", choices=("json", "text"), default="text")
    sub.choices["setup"].add_argument("--verbose", action="store_true")
    profiles_parser = sub.add_parser("profiles")
    profiles_parser.add_argument("--format", choices=("json", "text"), default="text")
    for name in ("clusters", "warehouses"):
        command = sub.add_parser(name)
        command.add_argument("--profile")
        command.add_argument("resource_action", nargs="?", choices=("list", "get"), default="list")
        command.add_argument("resource_id", nargs="?")
    for name in ("jobs", "pipelines"):
        command = sub.add_parser(name)
        command.add_argument("operation", choices=("list", "get"))
        command.add_argument("resource_id", nargs="?")
        command.add_argument("--profile")
    workspace_parser = sub.add_parser("workspace")
    workspace_parser.add_argument("operation", choices=("list",), default="list", nargs="?")
    workspace_parser.add_argument("path", nargs="?", default="/")
    workspace_parser.add_argument("--profile")
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
            result = setup(dry_run=args.dry_run, reset=args.reset)
            print(json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json"
                  else presentation.setup_text(result, verbose=args.verbose))
            return 0 if args.dry_run or result.get("overall") in {"READY", "DEGRADED"} else 1
        if args.action == "status":
            value = local_status() if args.local else status()
            print(json.dumps(value, indent=2) if args.format == "json" else status_text(value, verbose=args.verbose))
            return 0
        if args.action == "capabilities":
            value = capabilities(local_status())
            if args.format == "json":
                print(json.dumps(value, indent=2))
            else:
                print(presentation.capabilities_text(value))
            return 0
        if args.action == "profiles":
            profiles = discover_profiles()
            print(json.dumps(profiles, indent=2) if args.format == "json" else "\n".join(f"{p['name']}\t{p['workspace_host'] or 'account profile'}\t{'YES' if p['valid'] else 'NO'}" for p in profiles))
            return 0
        if args.action in {"clusters", "warehouses"}:
            if args.resource_action == "get":
                if not args.resource_id:
                    raise DatabricksError("INVALID_INPUT", f"{args.action} get requires a resource ID")
                selected, _, _ = resolve_profile(args.profile)
                result = json_from_cli([args.action, "get", args.resource_id], profile=selected)
            else:
                result = discover_clusters(args.profile) if args.action == "clusters" else discover_warehouses(args.profile)
            print(render_approval_state(result))
            return 0
        if args.action in {"jobs", "pipelines"}:
            if args.operation == "get" and not args.resource_id:
                raise DatabricksError("INVALID_INPUT", f"{args.action} get requires a resource ID")
            selected, _, _ = resolve_profile(args.profile)
            arguments = [args.action, args.operation]
            if args.resource_id:
                arguments.append(args.resource_id)
            print(render_approval_state(json_from_cli(arguments, profile=selected)))
            return 0
        if args.action == "workspace":
            selected, _, _ = resolve_profile(args.profile)
            print(render_approval_state(json_from_cli(["workspace", "list", args.path], profile=selected)))
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
        if args.action == "setup":
            if args.format == "json":
                print(json.dumps({"overall": "NOT_CONFIGURED", "error": {"category": category}}, indent=2))
            else:
                print(presentation.setup_error_text(category))
            return 1
        print(f"ERROR {category}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
