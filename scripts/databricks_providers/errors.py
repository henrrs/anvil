"""Normalized, secret-safe provider error semantics."""

from __future__ import annotations

import re
from typing import Any


POLICIES: dict[str, dict[str, Any]] = {
    "CLI_PROCESS_TIMEOUT": {"scope": "PROVIDER_SPECIFIC", "fallback_allowed": True},
    "CLI_EXECUTION_FAILED": {"scope": "UNKNOWN", "fallback_allowed": False},
    "CLI_OUTPUT_INVALID": {"scope": "PROVIDER_SPECIFIC", "fallback_allowed": True},
    "SDK_PROCESS_TIMEOUT": {"scope": "PROVIDER_SPECIFIC", "fallback_allowed": True},
    "PROVIDER_OUTPUT_INVALID": {"scope": "PROVIDER_SPECIFIC", "fallback_allowed": True},
    "CLI_ARGUMENT_ERROR": {"scope": "PROVIDER_SPECIFIC", "fallback_allowed": False},
    "AUTH_REQUIRED": {"scope": "SHARED_DEPENDENCY", "fallback_allowed": False},
    "AUTH_INVALID": {"scope": "SHARED_DEPENDENCY", "fallback_allowed": False},
    "AUTH_TIMEOUT": {"scope": "SHARED_DEPENDENCY", "fallback_allowed": False},
    "AUTH_CANCELLED": {"scope": "SHARED_DEPENDENCY", "fallback_allowed": False},
    "WORKSPACE_NETWORK_TIMEOUT": {"scope": "SHARED_DEPENDENCY", "fallback_allowed": False},
    "WORKSPACE_UNREACHABLE": {"scope": "SHARED_DEPENDENCY", "fallback_allowed": False},
    "PERMISSION_DENIED": {"scope": "CAPABILITY", "fallback_allowed": False},
    "PROVIDER_NOT_INSTALLED": {"scope": "PROVIDER_SPECIFIC", "fallback_allowed": True},
    "PROVIDER_BLOCKED": {"scope": "PROVIDER_SPECIFIC", "fallback_allowed": True},
    "PROVIDER_UNHEALTHY": {"scope": "PROVIDER_SPECIFIC", "fallback_allowed": True},
    "CAPABILITY_UNAVAILABLE": {"scope": "CAPABILITY", "fallback_allowed": False},
    "CAPABILITY_NOT_VERIFIED": {"scope": "CAPABILITY", "fallback_allowed": False},
    "CONFIG_INVALID": {"scope": "CONFIGURATION", "fallback_allowed": False},
    "PROFILE_INVALID": {"scope": "CONFIGURATION", "fallback_allowed": False},
}


VENDOR_CODE_CATEGORIES = {
    "PERMISSION_DENIED": "PERMISSION_DENIED",
    "PERMISSIONDENIED": "PERMISSION_DENIED",
    "UNAUTHENTICATED": "AUTH_INVALID",
    "INVALID_ACCESS_TOKEN": "AUTH_INVALID",
    "AUTH_REQUIRED": "AUTH_REQUIRED",
    "AUTHENTICATION_REQUIRED": "AUTH_REQUIRED",
    "WORKSPACE_NETWORK_TIMEOUT": "WORKSPACE_NETWORK_TIMEOUT",
    "REQUEST_TIMEOUT": "WORKSPACE_NETWORK_TIMEOUT",
    "WORKSPACE_UNREACHABLE": "WORKSPACE_UNREACHABLE",
}


class DatabricksError(RuntimeError):
    def __init__(self, category: str, message: str, *, provider: str | None = None,
                 operation: str | None = None, profile: str | None = None,
                 executable: str | None = None,
                 timeout_seconds: float | None = None, elapsed_ms: int | None = None,
                 failure_scope: str | None = None, fallback_allowed: bool | None = None,
                 diagnostics: dict[str, Any] | None = None):
        super().__init__(message)
        self.category = category
        self.provider = provider
        self.operation = operation
        self.profile = profile
        self.executable = executable
        self.timeout_seconds = timeout_seconds
        self.elapsed_ms = elapsed_ms
        policy = POLICIES.get(category, {})
        self.failure_scope = failure_scope or policy.get("scope", "OPERATION")
        self.fallback_allowed = (policy.get("fallback_allowed", False)
                                 if fallback_allowed is None else fallback_allowed)
        self.diagnostics = safe_diagnostics(diagnostics or {})


_SAFE_PHASES = {"initialization", "authentication_configuration", "request", "response_parsing"}
_SAFE_SCOPES = {"PROVIDER_SPECIFIC", "SHARED_DEPENDENCY", "CAPABILITY", "CONFIGURATION", "OPERATION", "UNKNOWN"}


def safe_diagnostics(value: Any) -> dict[str, Any]:
    """Copy only known, non-secret SDK failure fields across the worker boundary."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    phase = value.get("phase")
    if isinstance(phase, str) and phase in _SAFE_PHASES:
        result["phase"] = phase
    operation = value.get("operation")
    if isinstance(operation, str) and re.fullmatch(r"[a-z.]{1,48}", operation):
        result["operation"] = operation
    exception_category = value.get("exception_category")
    if isinstance(exception_category, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", exception_category):
        result["exception_category"] = exception_category
    status = value.get("normalized_status")
    if isinstance(status, int) and 400 <= status <= 599:
        result["normalized_status"] = status
    if isinstance(value.get("retryable"), bool):
        result["retryable"] = value["retryable"]
    scope = value.get("failure_scope")
    if isinstance(scope, str) and scope in _SAFE_SCOPES:
        result["failure_scope"] = scope
    return result


def vendor_category(value: Any) -> str | None:
    """Map only explicit structured Databricks/Azure error codes."""
    if not isinstance(value, str):
        return None
    return VENDOR_CODE_CATEGORIES.get(value.strip().upper().replace("-", "_"))
