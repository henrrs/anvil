"""Operation-specific Databricks time budgets.

Metadata requests get one bounded remote request budget that includes process
startup and Unified Authentication token acquisition. Long-running SQL and
Python work have separate budgets. Authentication may take longer, but remains
owned by the explicit setup flow.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimeoutPolicy:
    seconds: float
    reason: str


POLICIES = {
    "cli_version": TimeoutPolicy(5, "local executable version probe"),
    "auth_session": TimeoutPolicy(5, "local credential-session check"),
    "workspace_identity": TimeoutPolicy(45, "one read-only workspace request including cold token acquisition"),
    "provider_health": TimeoutPolicy(45, "one read-only provider request including startup and auth refresh"),
    "metadata_list": TimeoutPolicy(45, "bounded read-only metadata request"),
    "interactive_auth_idle": TimeoutPolicy(90, "explicit setup login inactivity watchdog"),
    "interactive_auth_max": TimeoutPolicy(180, "explicit setup login hard limit"),
    "sql_statement": TimeoutPolicy(120, "SQL statement execution; separate from request polling"),
    "remote_python": TimeoutPolicy(120, "remote Python command execution"),
    "long_operation_max": TimeoutPolicy(600, "hard cap for explicit long-running operations"),
    "worker_overhead": TimeoutPolicy(15, "local SDK/connector process teardown allowance"),
    "process_terminate_grace": TimeoutPolicy(1, "grace period before process-group kill"),
}


def seconds_for(operation_class: str) -> float:
    try:
        return POLICIES[operation_class].seconds
    except KeyError as exc:
        raise ValueError(f"unknown Databricks timeout class: {operation_class}") from exc
