"""Local-only signals used to choose a safe Databricks auth experience."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def detect_topology(*, environ: Mapping[str, str] | None = None, tty: bool | None = None,
                    cwd: str | None = None) -> dict[str, object]:
    env = dict(os.environ if environ is None else environ)
    interactive = bool(os.isatty(0)) if tty is None else tty
    path = str(Path(cwd or os.getcwd()).expanduser())
    vscode = any(env.get(key) for key in (
        "TERM_PROGRAM", "VSCODE_PID", "VSCODE_IPC_HOOK_CLI", "VSCODE_AGENT_FOLDER", "VSCODE_REMOTE",
    )) or "vscode-server" in path.casefold() or ".vscode-server" in path.casefold()
    remote_markers = any(env.get(key) for key in (
        "VSCODE_REMOTE", "VSCODE_AGENT_FOLDER", "SSH_CONNECTION", "SSH_TTY",
        "REMOTE_CONTAINERS", "CODESPACES", "CONTAINER",
    )) or "vscode-server" in path.casefold() or ".vscode-server" in path.casefold()
    if vscode and remote_markers:
        kind = "vscode_remote"
    elif env.get("SSH_CONNECTION") or env.get("SSH_TTY"):
        kind = "ssh"
    elif env.get("REMOTE_CONTAINERS") or env.get("CODESPACES") or env.get("CONTAINER"):
        kind = "container"
    elif env.get("CI") or not interactive:
        kind = "headless"
    elif vscode:
        kind = "vscode_local"
    elif env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        kind = "wsl"
    else:
        kind = "local"
    return {"kind": kind, "remote": kind in {"vscode_remote", "ssh", "container", "headless"},
            "interactive": interactive, "vscode_detected": vscode}


def workspace_cloud(host: str | None) -> str:
    from urllib.parse import urlsplit

    hostname = urlsplit(host or "").hostname or ""
    hostname = hostname.casefold().rstrip(".")
    if hostname.endswith(".azuredatabricks.net"):
        return "azure"
    if hostname.endswith(".gcp.databricks.com") or hostname.endswith(".gcp.databricks.eu"):
        return "gcp"
    if hostname.endswith(".cloud.databricks.com") or hostname.endswith(".databricks.com"):
        return "aws"
    return "unknown"
