"""Human-facing Databricks presenters; domain results remain structured."""

from __future__ import annotations

from typing import Any


def _cli_state(result: dict[str, Any]) -> str:
    providers = result.get("providers", {})
    return str(providers.get("cli", {}).get("status", "NOT_INSTALLED"))


def setup_text(result: dict[str, Any], *, verbose: bool = False) -> str:
    dry = bool(result.get("dry_run"))
    title = "Databricks Setup Plan" if dry else "Databricks Setup"
    lines = [title, "────────────────────────────────", ""]
    providers = result.get("providers", {})
    cli = providers.get("cli", {})
    sdk = providers.get("sdk", {})
    vscode = providers.get("vscode", {})
    overall = result.get("overall", "NOT_CONFIGURED")
    topology = result.get("topology", {}).get("kind", "unknown")
    workspace = result.get("workspace_host") or "not configured"
    profile = result.get("profile") or result.get("selected_profile") or "anvil-dev"
    environment = result.get("environment") or "development"
    cloud = result.get("cloud") or "unknown"
    lines += ["Workspace", f"  URL                  {workspace}", f"  Environment          {environment}",
              f"  Profile              {profile}", f"  Cloud                {cloud}",
              "", "Configuration", "  Ownership            Anvil",
              "  External profiles    not used or modified",
              "", "Environment", f"  Execution context    {topology.replace('_', ' ')}",
              f"  Databricks CLI       {'ready' if cli.get('status') == 'READY' else 'not installed' if not cli.get('installed') else 'unavailable'}",
              f"  Python SDK           {'ready' if sdk.get('status') == 'READY' else 'not installed'}",
              f"  VS Code integration  {'detected' if vscode.get('available') else 'not detected'}"]
    auth = result.get("authentication", {})
    if dry:
        lines += ["", "Authentication", f"  Recommended method   {str(auth.get('strategy', 'manual-auth')).replace('-', ' ')}",
                  f"  Reason               {auth.get('reason', 'Workspace cloud and session state are not configured yet.')}",
                  "", "Plan"]
        action = result.get("plan", [])
        if action:
            lines.extend(f"  {index}. {item}" for index, item in enumerate(action, 1))
        else:
            lines.extend(["  1. Install or reuse a supported provider", "  2. Authenticate and validate the workspace"])
        lines += ["", "DRY RUN — no changes performed."]
    else:
        lines.append("")
        if overall == "READY":
            lines += ["✓ Anvil-owned profile ready", "✓ Authentication validated", "✓ Workspace identity validated",
                      "✓ Databricks provider ready"]
        elif overall == "DEGRADED":
            lines += ["✓ Anvil-owned profile ready", "✓ Authentication validated", "✓ Workspace identity validated",
                      "Databricks providers are partially available"]
        else:
            lines += ["Databricks is not configured yet."]
        selected_provider = auth.get("provider") or ("cli" if cli.get("status") == "READY" else "sdk" if sdk.get("status") == "READY" else None)
        lines += ["", "Authentication", f"  Method               {str(auth.get('strategy', 'not configured')).replace('-', ' ')}",
                  f"  Status               {'READY' if overall in {'READY', 'DEGRADED'} else 'NOT_CONFIGURED'}"]
        if selected_provider and selected_provider != "preferred":
            lines += ["", "Execution", f"  Primary provider     {'Databricks CLI' if selected_provider == 'cli' else 'Python SDK'}",
                      f"  SDK fallback         {'available' if sdk.get('status') == 'READY' and selected_provider == 'cli' else 'not needed' if selected_provider == 'cli' else 'active'}"]
        if cli.get("status") == "READY" and not cli.get("path_visible"):
            lines += ["", "Note", "  CLI is ready for Anvil. It is not on this shell's PATH; no path change is needed."]
        conflicts = result.get("environment_conflicts", [])
        if conflicts:
            lines += ["", "Environment isolation", "  External DATABRICKS_* settings isolated:",
                      "  " + ", ".join(conflicts)]
        next_step = result.get("next_step")
        if next_step:
            lines += ["", "Next step", f"  {next_step}"]
        if result.get("auth_error"):
            category = str(result["auth_error"])
            message = {
                "AUTH_CANCELLED": "Authentication was cancelled.",
                "AUTH_TIMEOUT": "The supported login flow did not complete before its timeout.",
                "AUTH_REQUIRED": "The identity provider did not finish authentication.",
                "AUTH_PROVIDER_UNAVAILABLE": "The selected authentication provider is unavailable.",
                "IDENTITY_INVALID": "The workspace did not validate the signed-in identity.",
                "PROFILE_INVALID": "The saved workspace profile needs repair.",
                "PROFILE_VALIDATION_FAILED": "Databricks did not validate the new Anvil profile.",
                "PROFILE_OWNERSHIP_AMBIGUOUS": "Anvil found config data without ownership metadata and left it unchanged.",
                "PROFILE_COLLISION": "This Anvil profile name belongs to another workspace.",
                "PLAINTEXT_AUTH_STORAGE_UNSAFE": "The config contains a plaintext credential field; Anvil will not use it.",
                "WORKSPACE_REQUIRED": "A workspace URL is required for a new Anvil-owned configuration.",
                "AUTH_PROVIDER_UNAVAILABLE": "No supported Databricks provider is available.",
                "ENVIRONMENT_INVALID": "Choose a short environment label using letters, numbers, and hyphens.",
                "WORKSPACE_UNREACHABLE": "The selected workspace could not be reached or validated.",
                "WORKSPACE_PROFILE_INVALID": "Enter a valid HTTPS Databricks workspace URL.",
            }.get(category, "Authentication could not be completed.")
            lines += ["", message]
        lines += ["", f"Status                 {overall}"]
        if overall == "READY" and not next_step:
            lines += ["", "Try:", "  Ask Anvil to list available clusters and SQL warehouses."]
    if verbose:
        lines += ["", "Provider diagnostics"]
        for name in ("cli", "sdk", "sql_connector", "connect", "vscode"):
            item = providers.get(name, {})
            if item:
                lines.append(f"  {name:<18} {item.get('status', 'UNKNOWN')}")
                executable = item.get("executable") or item.get("python")
                if executable:
                    lines.append(f"    executable      {executable}")
        if result.get("workspace_host"):
            lines.append(f"  workspace           {result['workspace_host']}")
    return "\n".join(lines)


def setup_error_text(category: str) -> str:
    messages = {
        "PROFILE_OWNERSHIP_INVALID": ("Anvil operations require an Anvil-owned profile.",
                                      "Run make databricks-setup to create one without changing external profiles."),
        "CONFIG_OWNERSHIP_AMBIGUOUS": ("Anvil found config data at its managed path without ownership metadata.",
                                       "Anvil left it unchanged. Review the file or rerun with a separate XDG_CONFIG_HOME."),
        "CONFIG_INVALID": ("Anvil's managed config is invalid.",
                           "Run make databricks-setup RESET=1 to replace Anvil-owned config after validation."),
        "PROFILE_COLLISION": ("This Anvil profile name belongs to another workspace.",
                              "Choose a different environment label or use make databricks-setup RESET=1."),
        "PROFILE_INVALID": ("The Anvil-owned workspace profile needs authentication.",
                            "Rerun make databricks-setup to authenticate the selected Anvil workspace."),
        "PROFILE_MISSING": ("The Anvil-owned workspace profile is missing.",
                            "Rerun make databricks-setup to recreate it."),
        "PROFILE_CREATE_FAILED": ("Anvil could not safely prepare its workspace profile.",
                                  "Review permissions for the Anvil config directory, then rerun make databricks-setup."),
        "PROFILE_VALIDATION_FAILED": ("Databricks could not validate the staged Anvil profile.",
                                      "Check the workspace URL, sign-in session, and workspace access, then rerun setup."),
        "IDENTITY_INVALID": ("The signed-in identity could not be validated for this workspace.",
                             "Check the account and workspace permissions, then rerun make databricks-setup."),
        "AUTH_PROVIDER_UNAVAILABLE": ("No supported Databricks authentication provider is available.",
                                      "Allow the Databricks CLI or isolated SDK setup, then rerun make databricks-setup."),
        "AUTH_TIMEOUT": ("The supported login flow timed out.",
                         "Rerun make databricks-setup or use the official Databricks VS Code sign-in flow."),
        "AUTH_CANCELLED": ("Authentication was cancelled.", "Rerun make databricks-setup when ready."),
        "AUTH_FAILED": ("The identity provider could not complete authentication.", "Rerun make databricks-setup and select the supported sign-in method."),
        "AUTH_REQUIRED": ("No authentication completed for the selected workspace.", "Rerun make databricks-setup from a supported local or remote environment."),
        "WORKSPACE_REQUIRED": ("A workspace URL and environment are required.", "Run make databricks-setup from an interactive terminal."),
        "PLAINTEXT_AUTH_STORAGE_UNSAFE": ("A plaintext credential field was found in the Anvil config.", "Anvil left it unchanged; remove the field or reset only Anvil-owned config."),
        "WORKSPACE_PROFILE_INVALID": ("The workspace URL is not a valid HTTPS Databricks workspace.",
                                      "Rerun make databricks-setup and enter the workspace URL."),
    }
    message, next_step = messages.get(category, ("Databricks setup could not be completed.",
                                                   "Review the local setup state, then rerun make databricks-setup."))
    return "\n".join(["Databricks Setup", "────────────────────────────", "", message,
                      "", "Next step", f"  {next_step}", "", "Status                 NOT_CONFIGURED"])


def doctor_text(value: dict[str, Any], *, verbose: bool = False) -> str:
    overall = value.get("overall", "NOT_CONFIGURED")
    if value.get("auth_checked") is False:
        status = "not checked (local inventory only)"
    elif value.get("profile_valid") is True:
        status = "valid"
    else:
        status = "not configured"
    profile = value.get("selected_profile")
    lines = ["Databricks", f"  Status               {overall}", "", "Anvil configuration",
             f"  Profile              {profile or 'not configured'}",
             f"  Workspace            {'configured' if value.get('workspace_host') else 'not configured'}",
             f"  Authentication       {value.get('authentication_strategy') or status}"]
    if value.get("limitation"):
        lines.append(f"  Note                 {value['limitation']}")
    lines += ["", "External profiles",
              f"  Detected             {value.get('external_profiles_detected', 0)}",
              f"  Used by Anvil        {'YES' if value.get('external_profiles_used') else 'NO'}"]
    provider = "Databricks CLI" if value.get("cli_supported") else "Python SDK" if value.get("sdk_installed") else "none"
    if provider != "none":
        lines.append(f"  Primary provider     {provider}")
    if value.get("cli_supported") and not value.get("cli_path_visible"):
        lines.append("  PATH                 CLI is ready for Anvil; direct shell PATH access is optional")
    if verbose:
        lines += [f"  CLI version          {value.get('cli_version') or 'not installed'}",
                  f"  CLI executable       {value.get('cli_path') or 'not found'}",
                  f"  SDK version          {value.get('sdk_version') or 'not installed'}"]
        conflicts = value.get("environment_conflicts", [])
        if conflicts:
            lines.append("  Isolated overrides    " + ", ".join(conflicts))
    return "\n".join(lines)


def capabilities_text(value: dict[str, Any]) -> str:
    labels = {"Workspace API": "Workspace access", "Cluster discovery": "Cluster discovery",
              "Warehouse discovery": "SQL warehouses", "Remote Python": "Remote Python",
              "SQL": "SQL execution", "System tables": "System tables", "FinOps": "FinOps analysis",
              "Spark development": "Spark development", "Bundles": "Bundles"}
    lines = ["Databricks capabilities"]
    auth_not_checked = value.get("Authentication") == "NOT_CHECKED"
    for key, label in labels.items():
        state = value.get(key, "UNAVAILABLE")
        if state in {"UNAVAILABLE", "NOT_CONFIGURED", "NO", "LIMITED"}:
            result = "not configured" if state == "NOT_CONFIGURED" else "unavailable" if state in {"UNAVAILABLE", "NO"} else "limited"
        elif state == "NOT_CHECKED":
            result = "not checked"
        elif state == "ASSISTED":
            result = "available with VS Code"
        elif auth_not_checked:
            result = f"provider found · {state}; auth not checked"
        else:
            result = f"available · {state}"
        lines.append(f"  {label:<22} {result}")
    lines.append(f"  Overall               {value.get('Overall', 'NOT_CONFIGURED')}")
    lines.append("")
    lines.append("Authentication")
    lines.append(f"  Strategy              {str(value.get('Authentication strategy', 'NOT_CONFIGURED')).replace('-', ' ')}")
    lines.append(f"  Profile               {value.get('Anvil profile', 'NOT_CONFIGURED')}")
    return "\n".join(lines)
