"""Pure selection of documented Databricks authentication paths."""

from __future__ import annotations


def resolve(*, topology: dict[str, object], cloud: str, cli_ready: bool,
            sdk_ready: bool, azure_cli_available: bool, azure_cli_authenticated: bool,
            anvil_profile_valid: bool = False) -> dict[str, object]:
    provider = "cli" if cli_ready else "sdk" if sdk_ready else None
    if anvil_profile_valid and provider:
        return {"strategy": "anvil-profile", "provider": provider, "auth_required": False,
                "reason": "The selected Anvil-owned workspace profile is valid.", "fallbacks": []}
    remote = bool(topology.get("remote")) or topology.get("kind") in {"wsl", "unknown_hybrid"}
    interactive = bool(topology.get("interactive"))
    if cloud == "azure" and azure_cli_authenticated and provider:
        return {"strategy": "azure-cli-session", "provider": provider, "auth_required": False,
                "reason": "The Azure CLI session can be reused for this Azure workspace.",
                "fallbacks": ["databricks-cli-u2m"] if interactive and cli_ready else []}
    if cloud == "azure" and remote and azure_cli_available and provider:
        return {"strategy": "azure-cli-device-code", "provider": provider, "auth_required": True,
                "reason": "Azure CLI device-code authentication is supported for remote Azure workspaces.",
                "fallbacks": ["vscode-assisted", "manual-auth"]}
    if cloud == "azure" and azure_cli_available and interactive and provider:
        return {"strategy": "azure-cli-interactive", "provider": provider, "auth_required": True,
                "reason": "The Azure CLI can authenticate interactively and its session can be reused.",
                "fallbacks": ["databricks-cli-u2m"] if cli_ready else []}
    if cloud == "azure" and not remote and interactive and cli_ready:
        return {"strategy": "databricks-cli-u2m", "provider": "cli", "auth_required": True,
                "reason": "Azure CLI is unavailable; local Databricks OAuth U2M is the supported fallback.",
                "fallbacks": []}
    if remote:
        return {"strategy": "vscode-assisted" if topology.get("vscode_detected") else "manual-auth",
                "provider": "preferred", "auth_required": False,
                "reason": "No supported non-loopback cloud authentication is available in this remote session.",
                "fallbacks": ["vscode-assisted", "manual-auth"]}
    if interactive and cli_ready:
        return {"strategy": "databricks-cli-u2m", "provider": "cli", "auth_required": True,
                "reason": "The official Databricks CLI supports interactive OAuth U2M on this local terminal.",
                "fallbacks": []}
    return {"strategy": "manual-auth", "provider": "preferred", "auth_required": False,
            "reason": "No supported interactive authentication provider is available in this environment.",
            "fallbacks": ["vscode-assisted"] if topology.get("vscode_detected") else []}
