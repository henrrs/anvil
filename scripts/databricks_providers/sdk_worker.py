"""Isolated worker using official Databricks SDK APIs only."""

from __future__ import annotations

import json
import itertools
import os
import sys
import time
from datetime import timedelta
from typing import Any


def value_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "as_dict"):
        raw = value.as_dict()
    elif isinstance(value, dict):
        raw = value
    else:
        raw = {key: item for key, item in vars(value).items() if not key.startswith("_")}
    def normalize(item: Any) -> Any:
        if hasattr(item, "value"):
            return item.value
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalize(child) for child in item]
        return item
    return normalize(raw)


def bounded_collection(items: Any, key: str, limit: int = 200) -> dict[str, Any]:
    values = list(itertools.islice(items, limit + 1))
    return {key: [value_dict(item) for item in values[:limit]], "truncated": len(values) > limit}


def main() -> int:
    phase = "initialization"
    operation: str | None = None
    try:
        request = json.load(sys.stdin)
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.core import Config
        from databricks.sdk.service import compute, sql as sql_service

        profile = request.get("profile")
        if not isinstance(profile, str) or not profile.startswith("anvil-"):
            raise ValueError("SDK operations require an Anvil-owned profile")
        operation = request["operation"]
        payload = request.get("payload", {})
        timeout = max(5, min(int(request.get("timeout", 120)), 600))
        config_file = os.environ.get("DATABRICKS_CONFIG_FILE")
        if not config_file:
            raise ValueError("SDK operations require the explicit Anvil-owned config file")
        phase = "authentication_configuration"
        config = Config(profile=profile, config_file=config_file,
                        http_timeout_seconds=min(timeout, 60), retry_timeout_seconds=timeout)
        workspace = WorkspaceClient(config=config)

        def emit(value: Any) -> int:
            nonlocal phase
            phase = "response_parsing"
            print(json.dumps(value))
            return 0

        if operation == "identity":
            phase = "request"
            identity = value_dict(workspace.current_user.me())
            return emit({"identity": identity, "host": workspace.config.host})
        if operation == "clusters.list":
            phase = "request"
            return emit(bounded_collection(workspace.clusters.list(), "clusters"))
        if operation == "warehouses.list":
            phase = "request"
            return emit(bounded_collection(workspace.warehouses.list(), "warehouses"))
        if operation == "clusters.get":
            phase = "request"
            return emit(value_dict(workspace.clusters.get(cluster_id=payload["cluster_id"])))
        if operation == "warehouses.get":
            phase = "request"
            return emit(value_dict(workspace.warehouses.get(id=payload["warehouse_id"])))
        if operation == "jobs.list":
            phase = "request"
            return emit(bounded_collection(workspace.jobs.list(limit=200, expand_tasks=False), "jobs"))
        if operation == "jobs.get":
            phase = "request"
            job = workspace.jobs.get(job_id=int(payload["job_id"]))
            return emit(value_dict(job))
        if operation == "pipelines.list":
            phase = "request"
            return emit(bounded_collection(workspace.pipelines.list_pipelines(max_results=100), "pipelines"))
        if operation == "pipelines.get":
            phase = "request"
            return emit(value_dict(workspace.pipelines.get(pipeline_id=payload["pipeline_id"])))
        if operation == "workspace.list":
            phase = "request"
            return emit(bounded_collection(workspace.workspace.list(path=payload.get("path") or "/"), "objects"))
        if operation == "python.execute":
            phase = "request"
            cluster_id = payload["cluster_id"]
            context = workspace.command_execution.create_and_wait(cluster_id=cluster_id, language=compute.Language.PYTHON,
                                                                    timeout=timedelta(seconds=min(timeout, 120)))
            context_id = context.id
            waiter = None
            command_id = None
            try:
                waiter = workspace.command_execution.execute(cluster_id=cluster_id, context_id=context_id,
                                                              language=compute.Language.PYTHON, command=payload["code"])
                command_id = getattr(getattr(waiter, "response", None), "id", None)
                result = waiter.result(timeout=timedelta(seconds=timeout))
                return emit(value_dict(result))
            except TimeoutError:
                if command_id:
                    workspace.command_execution.cancel(cluster_id=cluster_id, context_id=context_id, command_id=command_id)
                raise RuntimeError("remote Python execution timed out")
            finally:
                workspace.command_execution.destroy(cluster_id=cluster_id, context_id=context_id)
        if operation == "sql.execute":
            phase = "request"
            api = workspace.statement_execution
            parameters = [sql_service.StatementParameterListItem(
                name=item["name"], type=item.get("type"),
                value=None if item.get("value") is None else str(item["value"]))
                for item in (payload.get("parameters") or []) if isinstance(item, dict) and item.get("name")]
            response = api.execute_statement(statement=payload["statement"], warehouse_id=payload["warehouse_id"],
                                             wait_timeout="10s", on_wait_timeout=sql_service.ExecuteStatementRequestOnWaitTimeout.CONTINUE,
                                             disposition=sql_service.Disposition.INLINE, format=sql_service.Format.JSON_ARRAY,
                                             row_limit=100, byte_limit=1_000_000, parameters=parameters or None)
            deadline = time.monotonic() + timeout
            while str(value_dict(response).get("status", {}).get("state", "")).upper() in {"PENDING", "RUNNING"}:
                if time.monotonic() >= deadline:
                    try:
                        api.cancel_execution(response.statement_id)
                    except Exception:
                        pass
                    raise RuntimeError("SQL statement timed out; cancellation was requested")
                time.sleep(1)
                response = api.get_statement(response.statement_id)
            return emit(value_dict(response))
        raise ValueError("unsupported SDK operation")
    except Exception as exc:
        exception_type = type(exc).__name__
        vendor_code = getattr(exc, "error_code", None)
        status_code = getattr(exc, "status_code", None)
        category = None
        if isinstance(exc, ValueError | KeyError):
            category = "CLI_ARGUMENT_ERROR"
        elif vendor_code == "PERMISSION_DENIED" or status_code == 403 or exception_type == "PermissionDenied":
            category = "PERMISSION_DENIED"
        elif vendor_code in {"UNAUTHENTICATED", "INVALID_ACCESS_TOKEN"} or status_code == 401 or exception_type in {
                "Unauthenticated", "UnauthenticatedError", "InvalidAccessTokenError"}:
            category = "AUTH_INVALID"
        elif exception_type in {"ReadTimeout", "ConnectTimeout", "DeadlineExceeded", "RequestTimeout", "TimeoutError"}:
            category = "WORKSPACE_NETWORK_TIMEOUT"
        elif exception_type in {"ConnectionError", "ServiceUnavailable"} or (isinstance(status_code, int) and status_code >= 500):
            category = "WORKSPACE_UNREACHABLE"
        else:
            category = "PROVIDER_UNHEALTHY"
        # Never return the SDK exception message; it can contain host,
        # workspace identifiers, request data, or credential details.
        if category in {"AUTH_REQUIRED", "AUTH_INVALID"}:
            phase = "authentication_configuration"
        status = status_code if isinstance(status_code, int) and 400 <= status_code <= 599 else None
        failure_scope = ("SHARED_DEPENDENCY" if category in {"AUTH_REQUIRED", "AUTH_INVALID", "WORKSPACE_NETWORK_TIMEOUT", "WORKSPACE_UNREACHABLE"}
                         else "CAPABILITY" if category == "PERMISSION_DENIED" else "PROVIDER_SPECIFIC")
        retryable = category in {"WORKSPACE_NETWORK_TIMEOUT", "WORKSPACE_UNREACHABLE"} or bool(status and status >= 500)
        operation_value = operation if isinstance(operation, str) and operation.replace(".", "").islower() else None
        print(json.dumps({"error": {"category": category, "summary": "Databricks SDK request failed",
                                     "phase": phase, "operation": operation_value,
                                     "exception_category": exception_type,
                                     "normalized_status": status,
                                     "retryable": retryable, "failure_scope": failure_scope}}),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
