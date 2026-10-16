"""Pure selection of documented Databricks authentication paths."""

from __future__ import annotations


def resolve(*, topology: dict[str, object], cloud: str, cli_ready: bool,
            sdk_ready: bool, azure_cli_available: bool, azure_cli_authenticated: bool,
            valid_profile: bool = False) -> dict[str, object]:
    if valid_profile:
        return {"strategy": "existing-profile", "provider": "preferred", "auth_required": False,
                "reason": "A previously validated Databricks profile is available."}
    remote = bool(topology.get("remote"))
    interactive = bool(topology.get("interactive"))
    if cloud == "azure" and azure_cli_authenticated and sdk_ready:
        return {"strategy": "azure-cli-session", "provider": "sdk", "auth_required": False,
                "reason": "The Azure CLI session can be reused for this Azure workspace."}
    if cloud == "azure" and remote and azure_cli_available and sdk_ready:
        return {"strategy": "azure-device-code", "provider": "sdk", "auth_required": True,
                "reason": "Azure CLI device-code authentication is supported for remote Azure workspaces."}
    if remote:
        return {"strategy": "vscode-assisted" if topology.get("vscode_detected") else "manual-profile",
                "provider": "preferred", "auth_required": False,
                "reason": "Browser callback authentication is not selected for a remote or headless session."}
    if interactive and cli_ready:
        return {"strategy": "databricks-cli-u2m", "provider": "cli", "auth_required": True,
                "reason": "The official Databricks CLI supports interactive OAuth U2M on this local terminal."}
    if cloud == "azure" and azure_cli_available and sdk_ready:
        return {"strategy": "azure-device-code", "provider": "sdk", "auth_required": True,
                "reason": "Azure CLI device-code authentication is available for this Azure workspace."}
    return {"strategy": "manual-profile", "provider": "preferred", "auth_required": False,
            "reason": "No supported interactive authentication provider is available in this environment."}
