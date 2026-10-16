"""Human-facing Databricks presenters; domain results remain structured."""

from __future__ import annotations

from typing import Any


def _cli_state(result: dict[str, Any]) -> str:
    providers = result.get("providers", {})
    return str(providers.get("cli", {}).get("status", "NOT_INSTALLED"))


def setup_text(result: dict[str, Any], *, verbose: bool = False) -> str:
    dry = bool(result.get("dry_run"))
    title = "Databricks Setup Plan" if dry else "Databricks Setup"
    lines = [title, "────────────────────────────", ""]
    providers = result.get("providers", {})
    cli = providers.get("cli", {})
    sdk = providers.get("sdk", {})
    vscode = providers.get("vscode", {})
    overall = result.get("overall", "NOT_CONFIGURED")
    topology = result.get("topology", {}).get("kind", "unknown")
    lines += ["Environment", f"  Development session  {topology.replace('_', ' ')}",
              f"  Databricks CLI       {'ready' if cli.get('status') == 'READY' else 'not installed' if not cli.get('installed') else 'unavailable'}",
              f"  Python SDK           {'ready' if sdk.get('status') == 'READY' else 'not installed'}",
              f"  VS Code integration  {'detected' if vscode.get('available') else 'not detected'}"]
    auth = result.get("authentication", {})
    if dry:
        lines += ["", "Authentication", f"  Existing profiles    {result.get('profiles_found', 0)}",
                  f"  Suggested method     {str(auth.get('strategy', 'manual-profile')).replace('-', ' ')}",
                  "", "Plan"]
        action = result.get("plan", [])
        if action:
            lines.extend(f"  {index}. {item}" for index, item in enumerate(action, 1))
        else:
            lines.extend(["  1. Install or reuse a supported provider", "  2. Authenticate and validate the workspace"])
        lines += ["", "No changes performed."]
    else:
        lines.append("")
        if overall == "READY":
            lines += ["✓ Databricks provider ready", "✓ Authentication validated", "✓ Workspace identity validated"]
        else:
            lines += ["Databricks is not configured yet."]
        profile = result.get("selected_profile")
        if profile:
            lines += ["", "Profile", f"  {profile}"]
        selected_provider = auth.get("provider") or ("cli" if cli.get("status") == "READY" else "sdk" if sdk.get("status") == "READY" else None)
        if selected_provider and selected_provider != "preferred":
            lines += ["", "Primary provider", f"  {'Databricks CLI' if selected_provider == 'cli' else 'Python SDK'}"]
        if cli.get("status") == "READY" and not cli.get("path_visible"):
            lines += ["", "Note", "  CLI is ready for Anvil. It is not on this shell's PATH; no path change is needed."]
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
        "PROFILE_SELECTION_REQUIRED": ("Several valid workspaces are available.",
                                        "Run make databricks-setup in an interactive terminal and select one."),
        "PROFILE_INVALID": ("The selected workspace profile needs authentication.",
                            "Rerun make databricks-setup to repair that same workspace."),
        "PROFILE_MISSING": ("The selected workspace profile is no longer available.",
                            "Rerun make databricks-setup to review the saved workspace."),
        "AUTH_TIMEOUT": ("The supported login flow timed out.",
                         "Rerun make databricks-setup or use the official Databricks VS Code sign-in flow."),
        "AUTH_CANCELLED": ("Authentication was cancelled.", "Rerun make databricks-setup when ready."),
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
    lines = ["Databricks", f"  Status               {overall}", f"  Authentication       {status}"]
    provider = "Databricks CLI" if value.get("cli_supported") else "Python SDK" if value.get("sdk_installed") else "none"
    if provider != "none":
        lines.append(f"  Primary provider     {provider}")
    if value.get("cli_supported") and not value.get("cli_path_visible"):
        lines.append("  PATH                 CLI is ready for Anvil; direct shell PATH access is optional")
    if value.get("limitation"):
        lines.append(f"  Note                 {value['limitation']}")
    if verbose:
        lines += [f"  CLI version          {value.get('cli_version') or 'not installed'}",
                  f"  CLI executable       {value.get('cli_path') or 'not found'}",
                  f"  SDK version          {value.get('sdk_version') or 'not installed'}"]
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
    return "\n".join(lines)
