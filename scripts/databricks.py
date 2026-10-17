#!/usr/bin/env python3
"""Secret-safe Databricks CLI adapter used by Anvil and its Databricks skill."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
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
from databricks_providers import errors, presentation, process, readiness, timeouts, topology  # noqa: E402


MINIMUM_CLI = (1, 0, 0)
MAX_SQL_ROWS = 100
MAX_SQL_BYTES = 1_000_000
MAX_RESULT_BYTES = 1_000_000
MAX_REMOTE_CODE_BYTES = 1_000_000
DEFAULT_TIMEOUT = int(timeouts.seconds_for("remote_python"))
POLL_INTERVAL = 1.0
DatabricksError = errors.DatabricksError


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


def _cli_operation(arguments: list[str]) -> str:
    if arguments and arguments[0] == "api" and len(arguments) >= 3:
        return " ".join(arguments[:3]).split("?", 1)[0]
    return " ".join(arguments[:2]) or "command"


def _structured_cli_error(stderr: str) -> str | None:
    try:
        value = json.loads(stderr)
    except (TypeError, json.JSONDecodeError):
        return None
    candidates = [value]
    if isinstance(value, dict):
        for key in ("error", "details", "status"):
            if isinstance(value.get(key), dict):
                candidates.append(value[key])
    for item in candidates:
        if isinstance(item, dict):
            for key in ("error_code", "code", "errorCode"):
                category = errors.vendor_category(item.get(key))
                if category:
                    return category
    return None


def run_cli(arguments: list[str], *, profile: str | None = None, timeout: float | None = None,
            stdin: str | None = None, config_path: Path | None = None) -> str:
    operation = _cli_operation(arguments)
    if timeout is None:
        operation_class = ("workspace_identity" if arguments[:2] == ["current-user", "me"] else
                           "metadata_list" if arguments[-1:] == ["list"] else "provider_health")
        timeout = timeouts.seconds_for(operation_class)
    try:
        binary, _ = require_cli()
    except DatabricksError as exc:
        raise DatabricksError("PROVIDER_NOT_INSTALLED", "Databricks CLI provider is unavailable",
                              provider="cli", operation=operation, profile=profile) from exc
    command = [binary, *arguments]
    if profile:
        command.extend(["--profile", profile])
    try:
        result = process.run(command, input_text=stdin, timeout=timeout,
                             env=owned_config.child_environment(profile=profile, path=config_path))
    except process.ProcessFailure as exc:
        if exc.category == "CLI_PROCESS_TIMEOUT":
            seconds = f"{timeout:g}"
            message = f"Databricks CLI ({binary}) timed out after {seconds}s while running {operation}; failure scope PROVIDER_SPECIFIC"
            if profile:
                message += f" with profile {profile}"
            raise DatabricksError(exc.category, message, provider="cli", operation=operation,
                                  profile=profile, executable=binary, timeout_seconds=timeout,
                                  elapsed_ms=exc.elapsed_ms) from exc
        raise DatabricksError(exc.category, "Databricks CLI provider could not start or returned oversized output",
                              provider="cli", operation=operation, profile=profile, executable=binary,
                              timeout_seconds=timeout, elapsed_ms=exc.elapsed_ms) from exc
    except ValueError as exc:
        raise DatabricksError("CLI_ARGUMENT_ERROR", "Databricks CLI command arguments are invalid",
                              provider="cli", operation=operation, profile=profile) from exc
    if result.returncode != 0:
        category = _structured_cli_error(result.stderr)
        if category is None:
            category = "CLI_ARGUMENT_ERROR" if result.returncode == 2 else "CLI_EXECUTION_FAILED"
        message = {
            "AUTH_REQUIRED": "Databricks authentication is required; run make databricks-setup",
            "AUTH_INVALID": "Databricks authentication is invalid; run make databricks-setup",
            "WORKSPACE_NETWORK_TIMEOUT": "Databricks workspace request timed out",
            "WORKSPACE_UNREACHABLE": "Databricks workspace could not be reached",
            "PERMISSION_DENIED": "Databricks denied this operation for the selected identity",
            "CLI_ARGUMENT_ERROR": "Databricks CLI rejected the command arguments",
        }.get(category, f"Databricks CLI failed while running {operation} (exit {result.returncode})")
        raise DatabricksError(category, message, provider="cli", operation=operation, profile=profile)
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


def _validate_profile_identity(name: str, listed: dict[str, Any], *,
                               config_path: Path | None = None,
                               providers: dict[str, dict[str, Any]] | None = None,
                               authentication_strategy: str | None = None,
                               preferred_provider: str | None = None) -> tuple[str, dict[str, Any]]:
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
    call = json_from_cli(["current-user", "me"], profile=name,
                         timeout=timeouts.seconds_for("workspace_identity"),
                         config_path=config_path, with_metadata=True,
                         providers=providers, authentication_strategy=authentication_strategy,
                         preferred_provider=preferred_provider)
    response = call["value"]
    if isinstance(response, dict) and isinstance(response.get("identity"), dict):
        identity = response["identity"]
        response_host = response.get("host")
    else:
        identity = response if isinstance(response, dict) else {}
        response_host = configured_host
    identity_ok = any(identity.get(key) for key in ("userName", "user_name", "id", "applicationId"))
    try:
        identity_host = workspace_host(str(response_host or configured_host))
    except DatabricksError as exc:
        raise DatabricksError("PROFILE_INVALID", "Databricks identity response was for an invalid workspace",
                              provider=call.get("provider"), operation="identity", profile=name) from exc
    if identity_host != configured_host:
        raise DatabricksError("PROFILE_INVALID", "Databricks identity response did not match the Anvil workspace",
                              provider=call.get("provider"), operation="identity", profile=name)
    if not identity_ok:
        raise DatabricksError("IDENTITY_INVALID", "Databricks current-user response did not identify the active principal",
                              provider=call.get("provider"), operation="identity", profile=name)
    return configured_host, call


def validate_selected_profile(name: str, listed: dict[str, Any], *, config_path: Path | None = None,
                              providers: dict[str, dict[str, Any]] | None = None,
                              authentication_strategy: str | None = None,
                              preferred_provider: str | None = None) -> str:
    host, _ = _validate_profile_identity(name, listed, config_path=config_path, providers=providers,
                                         authentication_strategy=authentication_strategy,
                                         preferred_provider=preferred_provider)
    return host


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
    profiles = owned_config.read_profiles()
    listed = profile_by_name(profiles, str(selected))
    if listed is None:
        raise DatabricksError("PROFILE_MISSING", "the selected Anvil-owned workspace profile is missing; rerun make databricks-setup")
    host = workspace_host(str(listed.get("host") or ""))
    return str(selected), host, profiles


def _operation_route(arguments: list[str]) -> tuple[str, str, dict[str, Any]] | None:
    if arguments[:2] == ["current-user", "me"]:
        return "auth.status", "identity", {}
    if arguments[:2] == ["clusters", "list"]:
        return "compute.list", "clusters.list", {}
    if arguments[:2] == ["clusters", "get"] and len(arguments) > 2:
        return "compute.get", "clusters.get", {"cluster_id": arguments[2]}
    if arguments[:2] == ["warehouses", "list"]:
        return "warehouse.list", "warehouses.list", {}
    if arguments[:2] == ["warehouses", "get"] and len(arguments) > 2:
        return "warehouse.get", "warehouses.get", {"warehouse_id": arguments[2]}
    if arguments[:2] == ["jobs", "list"]:
        return "jobs.list", "jobs.list", {}
    if arguments[:2] == ["jobs", "get"] and len(arguments) > 2:
        return "jobs.get", "jobs.get", {"job_id": arguments[2]}
    if arguments[:2] == ["pipelines", "list"]:
        return "pipelines.list", "pipelines.list", {}
    if arguments[:2] == ["pipelines", "get"] and len(arguments) > 2:
        return "pipelines.get", "pipelines.get", {"pipeline_id": arguments[2]}
    if arguments[:2] == ["workspace", "list"]:
        return "workspace.list", "workspace.list", {"path": arguments[2] if len(arguments) > 2 else "/"}
    return None


def _auth_route(authentication_strategy: str | None = None,
                preferred_provider: str | None = None) -> tuple[str | None, set[str] | None]:
    prefs = load_preferences()
    authentication = prefs.get("authentication") if isinstance(prefs.get("authentication"), dict) else {}
    strategy = authentication_strategy or str(authentication.get("strategy") or "")
    preferred = preferred_provider or (authentication.get("provider")
                                       if authentication.get("provider") in {"cli", "sdk"} else None)
    allowed = {"cli", "sdk"} if strategy.startswith("azure-cli") else None
    return preferred, allowed


def _call_provider(capability: str, sdk_operation: str, cli_arguments: list[str], *,
                   profile: str, timeout: float | None = None, config_path: Path | None = None,
                   payload: dict[str, Any] | None = None, providers: dict[str, dict[str, Any]] | None = None,
                   authentication_strategy: str | None = None,
                   preferred_provider: str | None = None) -> dict[str, Any]:
    inventory = providers or provider_snapshot()
    preferred, allowed = _auth_route(authentication_strategy, preferred_provider)
    candidates = resolver.candidates(capability, inventory, preferred_provider=preferred,
                                     allowed_providers=allowed)
    rejected: list[dict[str, Any]] = resolver.candidate_rejections(
        capability, inventory, preferred_provider=preferred, allowed_providers=allowed)
    if not candidates:
        category = rejected[0]["category"] if rejected else "PROVIDER_NOT_INSTALLED"
        error = DatabricksError(category, f"No usable Databricks provider supports {capability}",
                                operation=sdk_operation, profile=profile)
        error.rejected_providers = rejected
        error.blocking_condition = category
        raise error
    started_all = time.monotonic()
    for index, name in enumerate(candidates):
        started = time.monotonic()
        try:
            if name == "cli":
                args = list(cli_arguments)
                if "--output" not in args and "-o" not in args:
                    args.extend(["--output", "json"])
                output = run_cli(args, profile=profile, timeout=timeout, config_path=config_path)
                try:
                    value = json.loads(output)
                except json.JSONDecodeError as exc:
                    raise DatabricksError("CLI_OUTPUT_INVALID", "Databricks CLI returned invalid structured output",
                                          provider="cli", operation=sdk_operation, profile=profile) from exc
            elif name == "sdk":
                value = sdk.call(sdk_operation, profile=profile,
                                 timeout=int(timeout or timeouts.seconds_for("provider_health")),
                                 config_path=str(config_path) if config_path else None,
                                 **sdk_auth_options(profile), **(payload or {}))
            else:
                continue
            return {
                "value": value,
                "provider": name,
                "capability": capability,
                "operation": sdk_operation,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "elapsed_ms": int((time.monotonic() - started_all) * 1000),
                "fallback_reason": (rejected[0]["category"] if rejected else None),
                "rejected_providers": rejected,
                "blocking_condition": None,
            }
        except DatabricksError as exc:
            rejected.append({"provider": name, "category": exc.category,
                             "failure_scope": exc.failure_scope})
            if not exc.fallback_allowed or index + 1 >= len(candidates):
                exc.rejected_providers = rejected
                exc.blocking_condition = exc.category
                raise
    raise DatabricksError("PROVIDER_UNHEALTHY", f"No Databricks provider completed {sdk_operation}",
                          operation=sdk_operation, profile=profile)


def _record_runtime_outcome(profile: str, capability: str, *, provider: str | None = None,
                            result: Any = None, error: DatabricksError | None = None,
                            resolution: dict[str, Any] | None = None) -> None:
    """Persist fresh capability evidence and invalidate stale readiness on failure."""
    try:
        state = load_preferences()
        readiness_state = state.get("readiness")
        ownership = _profile_metadata(state)
        if not isinstance(readiness_state, dict) or ownership.get("name") != profile:
            return
        capabilities = readiness_state.setdefault("capabilities", {})
        checked_at = readiness.now()
        authentication = readiness_state.setdefault("authentication", {})
        workspace = readiness_state.setdefault("workspace", {})
        provider_record = readiness_state.setdefault("provider", {})
        blockers = [item for item in readiness_state.get("blockers", []) if isinstance(item, dict)]
        if error is None:
            item = capabilities.setdefault(capability, {"supported": True})
            item.update({"supported": True, "available": True, "verified": True,
                         "checked": True, "provider": provider, "validated_at": checked_at,
                         "failure_category": None, "blocked_by": None})
            provider_record.update({"status": "READY", "selected": provider or provider_record.get("selected"),
                                    "validated_at": checked_at,
                                    "failure_category": None,
                                    "validation_probe": error.operation if error else capability})
            if capability == "compute.list":
                item["resource_count"] = len(item_list(result, "clusters"))
            elif capability == "warehouse.list":
                item["resource_count"] = len(item_list(result, "warehouses", "endpoints"))
        else:
            item = capabilities.setdefault(capability, {"supported": True})
            item.update({"supported": True, "checked": True, "verified": False,
                         "available": False if error.category == "PERMISSION_DENIED" else None,
                         "provider": error.provider or provider, "validated_at": checked_at,
                         "failure_category": error.category, "blocked_by": error.category})
            policy_scope = error.failure_scope
            if error.category in {"AUTH_REQUIRED", "AUTH_INVALID", "AUTH_TIMEOUT", "AUTH_CANCELLED"}:
                authentication.update({"status": "FAILED", "failure_category": error.category,
                                      "validated_at": checked_at})
                workspace.update({"status": "NOT_VALIDATED", "failure_category": error.category,
                                  "validated_at": checked_at})
            elif error.category in {"WORKSPACE_NETWORK_TIMEOUT", "WORKSPACE_UNREACHABLE"}:
                workspace.update({"status": "FAILED", "failure_category": error.category,
                                  "validated_at": checked_at})
            elif policy_scope == "PROVIDER_SPECIFIC":
                provider_record.update({"status": "FAILED", "failure_category": error.category,
                                        "selected": error.provider or provider_record.get("selected"),
                                        "validated_at": checked_at})
            blockers = [item for item in blockers if item.get("operation") != (error.operation or capability)]
            blockers.append({"category": error.category, "scope": policy_scope,
                             "operation": error.operation or capability,
                             "summary": str(error)})
        if resolution:
            state["provider_resolution"] = resolution
        # Recompute all public state through the same readiness engine used by
        # setup and status. A capability failure must not be relabelled as an
        # authentication or workspace failure unless its normalized scope says so.
        refreshed = readiness.evaluate(
            configured=True, authentication=authentication, workspace=workspace,
            provider=provider_record, capabilities=capabilities, blockers=blockers,
            checked_at=checked_at)
        readiness_state.update(refreshed)
        state["capabilities"] = capabilities
        provider_state.save_state(state)
    except (DatabricksError, OSError, ValueError):
        # A workspace call's result/error must not be replaced by an
        # observability write failure. The next status command revalidates.
        return


def json_from_cli(arguments: list[str], *, profile: str, timeout: float | None = None,
                  config_path: Path | None = None, with_metadata: bool = False,
                  providers: dict[str, dict[str, Any]] | None = None,
                  authentication_strategy: str | None = None,
                  preferred_provider: str | None = None) -> Any:
    route = _operation_route(arguments)
    if route:
        capability, operation, payload = route
        if capability == "auth.status":
            timeout = timeout or timeouts.seconds_for("workspace_identity")
        elif capability in {"compute.list", "warehouse.list"}:
            timeout = timeout or timeouts.seconds_for("metadata_list")
        else:
            timeout = timeout or timeouts.seconds_for("provider_health")
        try:
            call = _call_provider(capability, operation, arguments, profile=profile, timeout=timeout,
                                  config_path=config_path, payload=payload, providers=providers,
                                  authentication_strategy=authentication_strategy,
                                  preferred_provider=preferred_provider)
        except DatabricksError as exc:
            if config_path is None:
                _record_runtime_outcome(profile, capability, error=exc)
            raise
        if config_path is None:
            _record_runtime_outcome(profile, capability, provider=call["provider"],
                                    result=call["value"],
                                    resolution={key: call[key] for key in (
                                        "provider", "capability", "operation", "latency_ms",
                                        "elapsed_ms", "fallback_reason", "rejected_providers",
                                        "blocking_condition")})
        return call if with_metadata else call["value"]
    output = run_cli([*arguments, "--output", "json"], profile=profile, timeout=timeout,
                     config_path=config_path)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise DatabricksError("CLI_OUTPUT_INVALID", "Databricks CLI returned invalid structured output",
                              provider="cli", operation=_cli_operation(arguments), profile=profile) from exc


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


def discover_clusters(profile: str | None = None, *, timeout: float | None = None) -> dict[str, Any]:
    selected, host, _ = resolve_profile(profile)
    data = json_from_cli(["clusters", "list"], profile=selected, timeout=timeout)
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


def discover_warehouses(profile: str | None = None, *, timeout: float | None = None) -> dict[str, Any]:
    selected, host, _ = resolve_profile(profile)
    data = json_from_cli(["warehouses", "list"], profile=selected, timeout=timeout)
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


def _resource_capability(profile: str, host: str, name: str,
                         providers: dict[str, dict[str, Any]], authentication: dict[str, Any],
                         config_path: Path | None = None,
                         preferred_provider: str | None = None) -> dict[str, Any]:
    action = "clusters list" if name == "compute.list" else "warehouses list"
    keys = ["clusters"] if name == "compute.list" else ["warehouses", "endpoints"]
    args = action.split()
    try:
        call = json_from_cli(args, profile=profile, config_path=config_path,
                             timeout=timeouts.seconds_for("provider_health"), with_metadata=True,
                             providers=providers,
                             authentication_strategy=str(authentication.get("strategy") or ""),
                             preferred_provider=preferred_provider or authentication.get("provider"))
        value = call["value"]
        if isinstance(value, list):
            raw_items = value
        elif isinstance(value, dict):
            raw_items = next((value[key] for key in keys if isinstance(value.get(key), list)), None)
        else:
            raw_items = None
        if raw_items is None:
            raise DatabricksError("CLI_OUTPUT_INVALID", f"Databricks {action} returned an invalid resource collection",
                                  provider=call.get("provider"), operation=action, profile=profile)
        if name == "compute.list":
            normalized = [item for raw in raw_items if isinstance(raw, dict)
                          and (item := normalized_cluster(raw))]
        else:
            normalized = [item for raw in raw_items if isinstance(raw, dict)
                          and (item := normalized_warehouse(raw))]
        return {
            "supported": True, "available": True, "verified": True, "checked": True,
            "provider": call["provider"], "operation": action, "probe": action,
            "validated_at": readiness.now(), "latency_ms": call["latency_ms"],
            "resource_count": len(raw_items), "failure_category": None,
            "running_count": sum(item.get("state") == "RUNNING" for item in normalized),
            "fallback_reason": call["fallback_reason"],
            "rejected_providers": call["rejected_providers"], "blocked_by": None,
        }
    except DatabricksError as exc:
        return {
            "supported": True,
            "available": False if exc.category == "PERMISSION_DENIED" else None,
            "verified": False, "checked": True,
            "provider": exc.provider or preferred_provider or authentication.get("provider"),
            "operation": action, "probe": action, "validated_at": readiness.now(),
            "latency_ms": exc.elapsed_ms, "resource_count": None,
            "failure_category": exc.category, "failure_scope": exc.failure_scope,
            "fallback_allowed": exc.fallback_allowed, "blocked_by": exc.category,
            "diagnostic_summary": str(exc), "executable": exc.executable,
            "timeout_seconds": exc.timeout_seconds, "elapsed_ms": exc.elapsed_ms,
            "rejected_providers": getattr(exc, "rejected_providers", []),
        }


def _probe_readiness(profile: str, host: str, config_path: Path | None,
                     providers: dict[str, dict[str, Any]],
                     authentication: dict[str, Any]) -> dict[str, Any]:
    identity_started = time.monotonic()
    try:
        identity_call = json_from_cli(["current-user", "me"], profile=profile,
                                      timeout=timeouts.seconds_for("workspace_identity"),
                                      config_path=config_path, with_metadata=True,
                                      providers=providers,
                                      authentication_strategy=str(authentication.get("strategy") or ""),
                                      preferred_provider=authentication.get("provider"))
        identity_value = identity_call["value"]
        if isinstance(identity_value, dict) and isinstance(identity_value.get("identity"), dict):
            identity = identity_value["identity"]
            response_host = identity_value.get("host") or host
        else:
            identity = identity_value if isinstance(identity_value, dict) else {}
            response_host = host
        identity_host = workspace_host(str(response_host))
        if identity_host != host or not any(identity.get(key) for key in
                                            ("userName", "user_name", "id", "applicationId")):
            raise DatabricksError("IDENTITY_INVALID", "Databricks current-user response did not validate this Anvil workspace",
                                  provider=identity_call["provider"], operation="identity", profile=profile)
        identity_provider = identity_call["provider"]
        auth_check = {"status": "READY", "strategy": authentication.get("strategy"),
                      "provider": identity_provider, "validated_at": readiness.now(),
                      "probe": "current-user"}
        workspace_check = {"status": "READY", "host": host, "provider": identity_provider,
                           "validated_at": readiness.now(), "probe": "current-user"}
        provider_check = {
            "selected": identity_provider, "status": "READY", "installed": True,
            "configured": True, "auth_accessible": True, "workspace_accessible": True,
            "latency_ms": identity_call["latency_ms"], "failure_category": None,
            "validation_probe": "current-user", "validated_at": readiness.now(),
            "fallback_reason": identity_call["fallback_reason"],
            "rejected_providers": identity_call["rejected_providers"],
            "diagnostic_summary": "Current-user request completed through the production provider adapter",
        }
    except DatabricksError as exc:
        category = exc.category
        auth_status = "FAILED" if category in {"AUTH_REQUIRED", "AUTH_INVALID"} else "UNKNOWN"
        auth_check = {"status": auth_status, "strategy": authentication.get("strategy"),
                      "provider": exc.provider, "failure_category": category,
                      "validated_at": readiness.now(), "probe": "current-user"}
        workspace_check = {"status": "NOT_VALIDATED", "host": host, "provider": exc.provider,
                           "failure_category": category, "validated_at": readiness.now(),
                           "probe": "current-user"}
        provider_status = "FAILED" if exc.failure_scope == "PROVIDER_SPECIFIC" else "NOT_VALIDATED"
        provider_check = {
            "selected": exc.provider or authentication.get("provider"), "status": provider_status,
            "installed": bool(exc.provider), "configured": True,
            "auth_accessible": auth_status == "READY", "workspace_accessible": False,
            "latency_ms": exc.elapsed_ms or int((time.monotonic() - identity_started) * 1000),
            "failure_category": category, "validation_probe": "current-user",
            "validated_at": readiness.now(), "diagnostic_summary": str(exc),
            "fallback_reason": None, "rejected_providers": getattr(exc, "rejected_providers", []),
        }
        blocker = {"category": category, "scope": exc.failure_scope,
                   "operation": "identity", "summary": str(exc)}
        capabilities = {
            "compute.list": {"supported": True, "available": None, "verified": False,
                             "checked": True, "resource_count": None, "blocked_by": category,
                             "failure_category": None},
            "warehouse.list": {"supported": True, "available": None, "verified": False,
                               "checked": True, "resource_count": None, "blocked_by": category,
                               "failure_category": None},
        }
        result = readiness.evaluate(configured=True, authentication=auth_check,
                                    workspace=workspace_check, provider=provider_check,
                                    capabilities=capabilities, blockers=[blocker])
        result["provider_resolution"] = {"provider": provider_check["selected"],
                                         "capability": "auth.status",
                                         "fallback_reason": None,
                                         "rejected_providers": provider_check["rejected_providers"],
                                         "blocking_condition": category}
        result["identity_error"] = category
        return result

    capability_checks: dict[str, dict[str, Any]] = {}
    blockers: list[dict[str, Any]] = []
    provider_failure: dict[str, Any] | None = None
    preferred = identity_provider
    for name in readiness.CORE_CAPABILITIES:
        check = _resource_capability(profile, host, name, providers, authentication,
                                     config_path=config_path, preferred_provider=preferred)
        capability_checks[name] = check
        if check.get("verified"):
            preferred = check.get("provider") or preferred
        elif check.get("failure_category"):
            blockers.append({"category": check["failure_category"],
                             "scope": check.get("failure_scope", "CAPABILITY"),
                             "operation": check["operation"],
                             "summary": check.get("diagnostic_summary") or
                             f"{check['operation']} was not verified"})
            if check.get("failure_scope") == "SHARED_DEPENDENCY":
                workspace_check.update({"status": "FAILED",
                                        "failure_category": check["failure_category"],
                                        "validated_at": check.get("validated_at")})
            elif check.get("failure_category") != "PERMISSION_DENIED":
                provider_failure = check
            if check.get("failure_scope") != "CAPABILITY":
                for remaining in readiness.CORE_CAPABILITIES:
                    if remaining in capability_checks:
                        continue
                    capability_checks[remaining] = {
                        "supported": True, "available": None, "verified": False,
                        "checked": True, "resource_count": None, "provider": preferred,
                        "operation": ("clusters list" if remaining == "compute.list" else "warehouses list"),
                        "validated_at": readiness.now(), "blocked_by": check["failure_category"],
                        "failure_category": None,
                    }
                break

    if provider_failure:
        provider_check["status"] = "FAILED"
        provider_check["failure_category"] = provider_failure.get("failure_category")
        provider_check["diagnostic_summary"] = provider_failure.get("diagnostic_summary") or (
            f"{provider_failure['operation']} failed through the selected production provider")
        provider_check["selected"] = provider_failure.get("provider") or provider_check["selected"]
    elif any(item.get("verified") for item in capability_checks.values()):
        provider_check["selected"] = preferred
    if all(item.get("verified") for item in capability_checks.values()):
        provider_check["validation_probe"] = "current-user + clusters list + warehouses list"
    else:
        provider_check["validation_probe"] = "current-user + capability probes"
    provider_check["capability_results"] = {
        name: {"verified": item.get("verified"), "resource_count": item.get("resource_count"),
               "failure_category": item.get("failure_category"), "provider": item.get("provider")}
        for name, item in capability_checks.items()
    }
    result = readiness.evaluate(configured=True, authentication=auth_check,
                                workspace=workspace_check, provider=provider_check,
                                capabilities=capability_checks, blockers=blockers)
    result["provider_resolution"] = {
        "provider": preferred, "capability": "compute.list/warehouse.list",
        "fallback_reason": next((item.get("fallback_reason") for item in capability_checks.values()
                                 if item.get("fallback_reason")), None),
        "rejected_providers": [rejected for item in capability_checks.values()
                               for rejected in item.get("rejected_providers", [])],
        "blocking_condition": blockers[0]["category"] if blockers else None,
    }
    return result


def _setup_summary(providers: dict[str, dict[str, Any]], profile: str, host: str,
                   config_path: Path | None, authentication: dict[str, Any]) -> dict[str, Any]:
    domain = _probe_readiness(profile, host, config_path, providers, authentication)
    return {
        "overall": domain["overall"], "readiness": domain,
        "selected_profile": profile,
        "external_profiles_detected": len(_external_profiles()), "external_profiles_used": False,
        "providers": providers, "capabilities": domain["capabilities"],
        "provider_resolution": domain.get("provider_resolution"),
        "blockers": domain.get("blockers", []),
    }


def _candidate_identity(profile: str, host: str, config_path: Path,
                        providers: dict[str, dict[str, Any]] | None = None,
                        decision: dict[str, Any] | None = None) -> tuple[str, str]:
    listed = {"name": profile, "host": host, "workspace_host": host,
              "workspace": True, "valid": True}
    strategy = str((decision or {}).get("strategy") or "")
    provider_hint = (decision or {}).get("provider")
    validated_host, call = _validate_profile_identity(
        profile, listed, config_path=config_path, providers=providers,
        authentication_strategy=strategy, preferred_provider=provider_hint)
    return validated_host, str(call["provider"])


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
        validated_host, provider = _candidate_identity(profile, host, config_path, providers, decision)
        auth_method = "azure-cli-session" if cloud == "azure" and strategy.startswith("azure-cli") else "unified-auth"
        config_record = next((item for item in owned_config.read_profiles(config_path)
                              if item["name"].casefold() == profile.casefold()), None)
        if (config_record or {}).get("auth_type") == "databricks-cli" or strategy == "databricks-cli-u2m":
            auth_method = "databricks-cli-u2m"
        return {"strategy": auth_method, "provider": provider, "cloud": cloud}, validated_host, None
    except DatabricksError as exc:
        if exc.category not in {"AUTH_REQUIRED", "AUTH_INVALID", "IDENTITY_INVALID"}:
            return None, None, exc.category

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
        validated_host, provider = _candidate_identity(profile, host, config_path, providers, decision)
    except DatabricksError as exc:
        return None, None, exc.category
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
                authentication = (dict(prefs["authentication"])
                                  if isinstance(prefs.get("authentication"), dict) else {})
                host, identity_provider = _candidate_identity(
                    name, safe_host, target, providers, authentication)
                authentication.setdefault("strategy", "unified-auth")
                authentication["provider"] = identity_provider
                authentication.setdefault("cloud", topology.workspace_cloud(host))
                summary = _setup_summary(providers, name, host, target, authentication)
                summary.update({"dry_run": False, "already_configured": True, "profile_created": False,
                                "profile": name,
                                "workspace_host": host, "environment": str((prefs.get("workspace") or {}).get("environment", "dev")),
                                "ownership": "Anvil", "cloud": topology.workspace_cloud(host),
                                "authentication": authentication,
                                "topology": topology.detect_topology(tty=sys.stdin.isatty()),
                                "environment_conflicts": owned_config.environment_conflicts(),
                                "credential_storage": "official Databricks/Azure authentication storage; Anvil stores metadata only"})
                if summary["overall"] not in {"READY", "DEGRADED"}:
                    summary["auth_error"] = (summary.get("blockers") or [{}])[0].get(
                        "category", "PROVIDER_UNHEALTHY")
                    summary["next_step"] = "The existing profile was left unchanged. Review the blocker, then rerun make databricks-setup."
                refreshed_state = load_preferences()
                refreshed_state["readiness"] = summary["readiness"]
                refreshed_state["capabilities"] = summary["capabilities"]
                refreshed_state["provider_resolution"] = summary["provider_resolution"]
                provider_state.save_state(refreshed_state)
                return summary
            except DatabricksError as exc:
                if exc.category not in {"AUTH_REQUIRED", "AUTH_INVALID", "IDENTITY_INVALID"}:
                    return {
                        "overall": "NOT_READY", "dry_run": False, "already_configured": True,
                        "selected_profile": name, "profile": name, "workspace_host": owned_record["host"],
                        "providers": providers, "auth_error": exc.category,
                        "blockers": [{"category": exc.category, "scope": exc.failure_scope,
                                      "operation": exc.operation or "identity", "summary": str(exc)}],
                        "next_step": "The existing Anvil config was left unchanged. Review the provider error, then rerun make databricks-setup.",
                        "external_profiles_detected": len(_external_profiles()), "external_profiles_used": False,
                    }

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
            summary = {"overall": "NOT_READY", "providers": providers,
                       "readiness": readiness.evaluate(
                           configured=False,
                           authentication={"status": "FAILED", "strategy": decision.get("strategy"),
                                           "failure_category": auth_error or "AUTH_REQUIRED"},
                           workspace={"status": "FAILED", "host": host},
                           provider={"status": "NOT_VALIDATED", "selected": decision.get("provider"),
                                     "failure_category": auth_error or "AUTH_REQUIRED"},
                           capabilities={}),
                       "capabilities": {}, "blockers": []}
            summary.update({"dry_run": False, "workspace_host": host, "environment": environment,
                           "profile": profile, "ownership": "Anvil", "auth_error": auth_error or "AUTH_FAILED",
                           "authentication": decision, "topology": environment_info,
                           "environment_conflicts": conflicts,
                           "next_step": "Resolve the authentication issue and rerun make databricks-setup."})
            return summary
        summary = _setup_summary(providers, profile, validated_host, stage, authentication)
        verified_core = summary["readiness"].get("verified_core_capabilities", [])
        if (summary["overall"] == "NOT_READY" or not verified_core
                or summary["readiness"].get("provider", {}).get("status") != "READY"):
            owned_config.discard_stage(stage)
            if not verified_core and summary["overall"] == "DEGRADED":
                summary["overall"] = "NOT_READY"
                summary["readiness"]["overall"] = "NOT_READY"
            root_blocker = (summary.get("blockers") or [{}])[0]
            summary.update({"dry_run": False, "workspace_host": validated_host,
                            "environment": environment, "profile": profile, "ownership": "Anvil",
                            "authentication": authentication, "topology": environment_info,
                            "environment_conflicts": conflicts,
                            "auth_error": root_blocker.get("category", "PROVIDER_UNHEALTHY"),
                            "next_step": "The candidate profile was not activated. Review the provider blocker, then rerun make databricks-setup."})
            return summary
        selected_provider = (summary.get("provider_resolution") or {}).get("provider")
        if selected_provider in {"cli", "sdk"}:
            authentication["provider"] = selected_provider
            summary["readiness"]["provider"]["selected"] = selected_provider
        backup = owned_config.backup_existing(reset=reset)
        owned_config.commit_staged(stage)
        try:
            _save_provider_snapshot(providers, install_result, sdk_install_result)
            path = save_preferences(profile, validated_host, authentication)
            state = load_preferences()
            state["capabilities"] = summary["capabilities"]
            state["readiness"] = summary["readiness"]
            state["provider_resolution"] = summary["provider_resolution"]
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
                    "next_step": (None if summary["overall"] == "READY" else
                                  "Review the blocked capability in make doctor output."
                                  if summary["overall"] == "DEGRADED" else
                                  "Check provider availability and rerun make databricks-setup.")})
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
    auth_record = prefs.get("authentication") if isinstance(prefs.get("authentication"), dict) else {}
    saved_readiness = prefs.get("readiness") if isinstance(prefs.get("readiness"), dict) else {}
    host = None
    profile_error = None
    if selected and value["profile_configured"]:
        record = next((item for item in owned_config.read_profiles()
                       if item["name"].casefold() == str(selected).casefold()), None)
        try:
            if not record:
                raise DatabricksError("PROFILE_MISSING", "the Anvil-owned workspace profile is missing")
            host = workspace_host(record.get("host", ""))
            saved_host = value.get("workspace_host")
            if saved_host and workspace_host(str(saved_host)) != host:
                raise DatabricksError("PROFILE_INVALID", "the selected Anvil profile no longer matches saved workspace metadata")
        except DatabricksError as exc:
            profile_error = exc
    if not selected or not value["profile_configured"] or profile_error:
        category = ("PROFILE_MISSING" if selected else "PROFILE_NOT_SELECTED") if profile_error is None else profile_error.category
        domain = readiness.evaluate(
            configured=False,
            authentication={"status": "NOT_CONFIGURED", "strategy": auth_record.get("strategy"),
                            "failure_category": category},
            workspace={"status": "NOT_CONFIGURED", "failure_category": category},
            provider={"selected": None, "status": "NOT_VALIDATED",
                      "installed": bool(cli_ready or sdk_state.get("status") == "READY"),
                      "configured": False, "auth_accessible": None,
                      "workspace_accessible": None, "failure_category": category},
            capabilities={
                "compute.list": {"supported": True, "available": None, "verified": False,
                                 "checked": False, "resource_count": None, "blocked_by": category},
                "warehouse.list": {"supported": True, "available": None, "verified": False,
                                   "checked": False, "resource_count": None, "blocked_by": category},
            })
        value["limitation"] = ("No Anvil-owned Databricks profile is configured; run make databricks-setup."
                               if not selected else "The Anvil-owned workspace profile is missing or invalid; rerun make databricks-setup.")
    else:
        authentication = {"strategy": auth_record.get("strategy", "unified-auth"),
                          "provider": auth_record.get("provider") or "cli",
                          "cloud": auth_record.get("cloud") or topology.workspace_cloud(host)}
        domain = _probe_readiness(str(selected), str(host), None, providers, authentication)
        value["workspace_host"] = host
        value["profile_valid"] = domain["authentication"].get("status") == "READY"
        value["identity_reachable"] = domain["workspace"].get("status") == "READY"
        value["running_all_purpose_compute"] = domain["capabilities"].get(
            "compute.list", {}).get("running_count")
        value["running_sql_warehouses"] = domain["capabilities"].get(
            "warehouse.list", {}).get("running_count")
        value["last_validation"] = domain.get("validated_at")
        if domain.get("blockers"):
            blocker = domain["blockers"][0]
            value["limitation"] = f"{blocker.get('operation')}: {blocker.get('category')}"
        if (domain.get("overall") in {"READY", "DEGRADED", "NOT_READY"}
                and domain.get("state") != "NOT_CONFIGURED"):
            refreshed = load_preferences()
            refreshed["readiness"] = domain
            refreshed["capabilities"] = domain["capabilities"]
            refreshed["provider_resolution"] = domain.get("provider_resolution")
            try:
                provider_state.save_state(refreshed)
            except (OSError, ValueError) as exc:
                value["state_persistence_error"] = "Databricks readiness could not be saved"
                if not value.get("limitation"):
                    value["limitation"] = str(exc)

    value["readiness"] = domain
    value["overall"] = domain["overall"]
    value["auth_checked"] = True
    value["workspace_checked"] = True
    auth_valid = domain["authentication"].get("status") == "READY"
    failed_provider = domain.get("provider", {}).get("selected")
    failures = ({failed_provider: str(domain.get("provider", {}).get("failure_category"))}
                if failed_provider and domain.get("provider", {}).get("status") == "FAILED" else {})
    value["resolved_capabilities"] = resolver.resolve(
        providers, auth_valid=auth_valid,
        preferred_provider=(domain.get("provider_resolution") or {}).get("provider"),
        provider_failures=failures)
    value["capability_health"] = domain.get("capabilities", {})
    if value.get("overall") == "DEGRADED" and not value.get("limitation"):
        value["limitation"] = "Some core capabilities are not verified; see the capability blockers."
    if value.get("overall") == "NOT_READY" and not value.get("limitation"):
        value["limitation"] = (domain.get("blockers") or [{}])[0].get(
            "summary", "Databricks readiness checks failed.")
    # status() has just performed a fresh production-path probe when a profile
    # is configured. The local-only command is responsible for TTL reporting.
    value["readiness_stale"] = (False if selected and not profile_error
                                else bool(saved_readiness and readiness.is_stale(saved_readiness)))
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
    cached = prefs.get("readiness") if isinstance(prefs.get("readiness"), dict) else None
    stale = readiness.is_stale(cached) if cached else True
    value["readiness"] = cached
    value["readiness_stale"] = stale
    value["capability_health"] = (cached or {}).get("capabilities", {})
    value["overall"] = ("STALE" if stale and cached and cached.get("overall") not in {"NOT_CONFIGURED", "NOT_READY"}
                        else cached.get("overall") if cached and not stale
                        else "NOT_CONFIGURED" if not selected else "NOT_CHECKED")
    return value


def status_text(value: dict[str, Any], *, verbose: bool = False) -> str:
    return presentation.doctor_text(value, verbose=verbose)


def capabilities(value: dict[str, Any]) -> dict[str, Any]:
    cap_map = value.get("resolved_capabilities", {})
    health = value.get("capability_health") or (value.get("readiness") or {}).get("capabilities", {})
    providers = {
        "cli": {"status": "READY"} if value.get("cli_supported") else {"status": "NOT_INSTALLED"},
        "sdk": {"status": "READY"} if value.get("sdk_installed") else {"status": "NOT_INSTALLED"},
        "sql_connector": value.get("sql_connector", {}),
        "connect": value.get("connect", {}),
        "vscode": value.get("vscode", {}),
    }
    auth_valid = value.get("profile_valid") is True and value.get("identity_reachable") is True
    readiness_state = value.get("readiness") or {}
    readiness_stale = bool(value.get("readiness_stale"))
    root_failure = ((readiness_state.get("provider") or {}).get("failure_category")
                    or (readiness_state.get("workspace") or {}).get("failure_category")
                    or (readiness_state.get("authentication") or {}).get("failure_category"))
    result: dict[str, Any] = {
        "overall": value.get("overall", "NOT_CHECKED"),
        "authentication": "READY" if auth_valid else "NOT_CHECKED" if value.get("auth_checked") is False else "NOT_CONFIGURED",
        "authentication_strategy": value.get("authentication_strategy") or "NOT_CONFIGURED",
        "profile": value.get("selected_profile") or "NOT_CONFIGURED",
        "readiness_stale": readiness_stale,
        "capabilities": {},
    }
    for capability, priority in resolver.CAPABILITY_ORDER.items():
        supported_providers = [name for name in priority
                               if capability in resolver.PROVIDER_CAPABILITIES.get(name, set())]
        evidence = health.get(capability, {})
        resolved = cap_map.get(capability, {})
        installed = next((name for name in supported_providers
                          if providers.get(name, {}).get("status") in {"READY", "AVAILABLE"}
                          and name != "vscode"), None)
        supported = bool(supported_providers)
        available = evidence.get("available")
        if capability not in health:
            if value.get("auth_checked") is False:
                available = True if installed or resolved.get("provider") else None
            elif not auth_valid:
                available = None
            else:
                available = bool(installed or resolved.get("provider"))
        verified = bool(evidence.get("verified")) and not readiness_stale
        blocker = evidence.get("blocked_by") or (
            root_failure if auth_valid is False and value.get("auth_checked") is not False else None)
        if capability == "system_tables.query" and value.get("running_sql_warehouses") == 0:
            available = False
            verified = False
            blocker = "no running SQL warehouse"
        result["capabilities"][capability] = {
            "supported": supported,
            "available": available,
            "verified": verified,
            "provider": evidence.get("provider") or resolved.get("provider") or installed,
            "validated_at": evidence.get("validated_at") if verified else None,
            "resource_count": evidence.get("resource_count"),
            "blocked_by": blocker,
            "fallback_reason": evidence.get("fallback_reason") or resolved.get("fallback_reason"),
            "rejected_providers": evidence.get("rejected_providers") or resolved.get("rejected_providers", []),
        }
    result["providers"] = {
        name: {"installed": item.get("status") in {"READY", "AVAILABLE"},
               "status": item.get("status", "UNKNOWN")}
        for name, item in providers.items()
    }
    return result


def render_approval_state(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


class DatabricksArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise DatabricksError("CLI_ARGUMENT_ERROR", "Databricks adapter command arguments are invalid; review the command usage")


def _bounded_timeout(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be an integer number of seconds") from exc
    if parsed < 5 or parsed > 600:
        raise argparse.ArgumentTypeError("timeout must be between 5 and 600 seconds")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = DatabricksArgumentParser(description=__doc__)
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
    profiles_parser.add_argument("--timeout", type=_bounded_timeout, default=60)
    for name in ("clusters", "warehouses"):
        command = sub.add_parser(name)
        command.add_argument("--profile")
        command.add_argument("resource_action", nargs="?", choices=("list", "get"), default="list")
        command.add_argument("resource_id", nargs="?")
        command.add_argument("--format", choices=("json",), default="json")
        command.add_argument("--timeout", type=_bounded_timeout)
    for name in ("jobs", "pipelines"):
        command = sub.add_parser(name)
        command.add_argument("operation", choices=("list", "get"))
        command.add_argument("resource_id", nargs="?")
        command.add_argument("--profile")
        command.add_argument("--format", choices=("json",), default="json")
        command.add_argument("--timeout", type=_bounded_timeout)
    workspace_parser = sub.add_parser("workspace")
    workspace_parser.add_argument("operation", choices=("list",), default="list", nargs="?")
    workspace_parser.add_argument("path", nargs="?", default="/")
    workspace_parser.add_argument("--profile")
    workspace_parser.add_argument("--format", choices=("json",), default="json")
    workspace_parser.add_argument("--timeout", type=_bounded_timeout)
    python_parser = sub.add_parser("python")
    python_parser.add_argument("--cluster-id", required=True)
    python_parser.add_argument("--profile")
    python_parser.add_argument("--timeout", type=_bounded_timeout, default=DEFAULT_TIMEOUT)
    python_parser.add_argument("--format", choices=("json",), default="json")
    sql_parser = sub.add_parser("sql")
    sql_parser.add_argument("--warehouse-id", required=True)
    sql_parser.add_argument("--profile")
    sql_parser.add_argument("--timeout", type=_bounded_timeout, default=DEFAULT_TIMEOUT)
    sql_parser.add_argument("--format", choices=("json",), default="json")
    sql_parser.add_argument("--parameters-json")
    sql_parser.add_argument("--allow-mutation", action="store_true", help="Use only after direct user approval for a write or configuration-changing statement")
    sql_parser.add_argument("statement", nargs="?")
    catalog_parser = sub.add_parser("system-catalog")
    catalog_parser.add_argument("--warehouse-id", required=True)
    catalog_parser.add_argument("--profile")
    catalog_parser.add_argument("--schema")
    catalog_parser.add_argument("--timeout", type=_bounded_timeout, default=DEFAULT_TIMEOUT)
    catalog_parser.add_argument("--format", choices=("json",), default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except DatabricksError as exc:
        print(f"ERROR {exc.category}: {exc}", file=sys.stderr)
        return 2
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
            profiles = discover_profiles(timeout=args.timeout)
            print(json.dumps(profiles, indent=2) if args.format == "json" else "\n".join(f"{p['name']}\t{p['workspace_host'] or 'account profile'}\t{'YES' if p['valid'] else 'NO'}" for p in profiles))
            return 0
        if args.action in {"clusters", "warehouses"}:
            if args.resource_action == "get":
                if not args.resource_id:
                    raise DatabricksError("INVALID_INPUT", f"{args.action} get requires a resource ID")
                selected, _, _ = resolve_profile(args.profile)
                result = json_from_cli([args.action, "get", args.resource_id], profile=selected,
                                       timeout=args.timeout)
            else:
                result = (discover_clusters(args.profile, timeout=args.timeout) if args.action == "clusters"
                          else discover_warehouses(args.profile, timeout=args.timeout))
            print(render_approval_state(result))
            return 0
        if args.action in {"jobs", "pipelines"}:
            if args.operation == "get" and not args.resource_id:
                raise DatabricksError("INVALID_INPUT", f"{args.action} get requires a resource ID")
            selected, _, _ = resolve_profile(args.profile)
            arguments = [args.action, args.operation]
            if args.resource_id:
                arguments.append(args.resource_id)
            print(render_approval_state(json_from_cli(arguments, profile=selected, timeout=args.timeout)))
            return 0
        if args.action == "workspace":
            selected, _, _ = resolve_profile(args.profile)
            print(render_approval_state(json_from_cli(["workspace", "list", args.path], profile=selected,
                                                       timeout=args.timeout)))
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
        print(render_approval_state(execute_sql(statement, args.warehouse_id, selected, timeout=args.timeout)))
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
