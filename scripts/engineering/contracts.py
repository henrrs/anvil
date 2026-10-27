"""Validate the three models; semantic extraction remains the agent's job."""

from __future__ import annotations

import copy
import json
import re
from pathlib import PurePosixPath
from typing import Any

from .errors import EngineeringError

REQUIREMENT_STATES = {"PENDING", "IN_PROGRESS", "IMPLEMENTED", "VERIFIED", "BLOCKED", "DEFERRED", "NOT_APPLICABLE"}
TASK_STATES = {"PENDING", "ACTIVE", "IMPLEMENTED", "VERIFIED", "BLOCKED", "DEFERRED", "NOT_APPLICABLE"}
CONFIDENCE = {"OBSERVED", "SUPPORTED", "INFERRED", "UNKNOWN"}
ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,79}\Z")
MAX_STATE_BYTES = 2 * 1024 * 1024


def require(condition: Any, message: str, code: str = "SPECIFICATION_INVALID") -> None:
    if not condition:
        raise EngineeringError(code, message)


def identifier(value: Any) -> str:
    require(isinstance(value, str) and ID.fullmatch(value), "IDs must start with a letter and contain at most 80 letters, digits, _ or -.")
    return value


def relative_path(value: Any, *, glob: bool = False) -> str:
    require(isinstance(value, str) and value and "\\" not in value, "Expected a repository-relative POSIX path.")
    path = PurePosixPath(value)
    require(not path.is_absolute() and not any(p in {"..", ".git"} for p in path.parts), "Paths must stay inside the repository and outside .git.")
    require(not any(p == ".env" or p.startswith(".env.") for p in path.parts), "Authentication/environment files must not enter engineering state.")
    require(glob or not any(c in value for c in "*?[]"), "Use explicit paths outside invariant scopes.")
    return value


def safe_content(value: Any) -> None:
    """Reject recognizable credential payloads; never collect environment or raw logs."""
    text = json.dumps(value, ensure_ascii=False)
    require(len(text.encode()) <= MAX_STATE_BYTES, "Engineering state exceeds the 2 MiB limit.")
    # Split signatures so repository secret scanners do not mistake test code for a credential.
    patterns = [r"(?i)Bearer\s+[A-Za-z0-9._~-]{12,}", r"gh" + r"[pousr]_[A-Za-z0-9_]{20,}",
                r"-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                r"(?i)(?:password|client_secret|access_token|api_key)\s*[:=]\s*[\"']?[A-Za-z0-9_./+~=-]{8,}",
                r"https?://[^\s/]+:[^\s/]+@"]
    require(not any(re.search(pattern, text) for pattern in patterns),
            "Recognizable credential material cannot be persisted in engineering state.")
    if isinstance(value, dict):
        require(not ({"credentials", "auth_state", "environment_dump", "raw_output", "raw_logs",
                      "password", "access_token", "client_secret", "api_key", "authorization"} & set(value)),
                "Raw authentication, environment, and process output do not belong in engineering state.")
        for item in value.values():
            safe_content(item)
    elif isinstance(value, list):
        for item in value:
            safe_content(item)


def indexed(items: Any, label: str) -> dict[str, dict]:
    require(isinstance(items, list), f"{label} must be a list.")
    result = {}
    for item in items:
        require(isinstance(item, dict), f"{label} entries must be objects.")
        key = identifier(item.get("id"))
        require(key not in result, f"Duplicate {label} ID: {key}")
        result[key] = item
    return result


def dependency_graph(items: dict[str, dict], label: str) -> None:
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(key: str) -> None:
        require(key not in visiting, f"Cyclic {label} dependency at {key}.", "BLOCKED_DEPENDENCY")
        if key in done:
            return
        visiting.add(key)
        dependencies = items[key].get("depends_on", [])
        require(isinstance(dependencies, list), f"{key} depends_on must be a list.")
        for parent in dependencies:
            require(parent in items, f"{key} references missing {label} dependency {parent}.", "BLOCKED_DEPENDENCY")
            visit(parent)
        visiting.remove(key)
        done.add(key)

    for key in items:
        visit(key)


def criteria(items: Any, checks: set[str], label: str) -> None:
    require(isinstance(items, list) and items, f"{label} needs explicit completion criteria.")
    for item in items:
        require(isinstance(item, dict) and item.get("statement"), f"{label} criterion needs a statement.")
        references = item.get("check_ids")
        require(isinstance(references, list) and references and set(references) <= checks,
                f"{label} criterion must reference existing verification checks.")


def _validate_models(models: Any) -> dict:
    require(isinstance(models, dict) and set(models) == {"requirements", "architecture", "work"},
            "Provide separate requirements, architecture, and work models.")
    safe_content(models)
    requirements, architecture, work = (models[k] for k in ("requirements", "architecture", "work"))
    require(all(isinstance(m, dict) for m in (requirements, architecture, work)), "Models must be objects.")
    require(bool(requirements.get("objective")), "A normalized objective is required.")
    reqs = indexed(requirements.get("items"), "requirement")
    require(reqs, "At least one explicit requirement is needed; keep trivial tasks on the direct path.")
    for key, item in reqs.items():
        require(item.get("statement") and item.get("type") and item.get("priority") in {"required", "optional"}, f"{key} needs statement, type, and priority.")
        source = item.get("source", {})
        require(isinstance(source, dict) and source.get("document") and source.get("section"), f"{key} needs source document and section provenance.")
        if "lines" in source:
            lines = source["lines"]
            require(isinstance(lines, list) and len(lines) == 2 and all(isinstance(n, int) and n > 0 for n in lines) and lines[1] >= lines[0], f"{key} has an invalid source line range.")
        require(item.get("status", "PENDING") in REQUIREMENT_STATES, f"{key} has an invalid requirement status.")
        if item.get("status") in {"DEFERRED", "NOT_APPLICABLE"}:
            require(item.get("disposition_reason"), f"{key} needs an explicit disposition reason.")
    boundaries = indexed(architecture.get("boundaries", []), "boundary")
    dependency_graph(boundaries, "boundary")
    for key, item in boundaries.items():
        require(item.get("owns") and isinstance(item.get("must_not_know", []), list), f"{key} needs responsibility ownership.")
    decisions = indexed(architecture.get("decisions", []), "decision")
    for key, item in decisions.items():
        require(item.get("context") and item.get("decision") and isinstance(item.get("consequences"), list), f"{key} needs context, decision, and consequences.")
        require(item.get("status", "VALID") in {"VALID", "AMENDED", "SUPERSEDED"}, f"{key} has an invalid decision status.")
    invariants = indexed(architecture.get("invariants", []), "invariant")
    for key, item in invariants.items():
        require(item.get("statement") and item.get("kind") in {"forbidden_imports", "forbidden_text", "required_files", "semantic"}, f"{key} needs an invariant statement and supported kind.")
        require(isinstance(item.get("paths"), list) and item["paths"], f"{key} needs an explicit scope.")
        for path in item["paths"]:
            relative_path(path, glob=True)
        if item["kind"] in {"forbidden_imports", "forbidden_text"}:
            require(isinstance(item.get("forbidden"), list) and item["forbidden"] and all(isinstance(s, str) and s for s in item["forbidden"]), f"{key} needs forbidden dependencies/text.")
    for unknown in indexed(architecture.get("unknowns", []), "unknown").values():
        require(unknown.get("question") and isinstance(unknown.get("blocking"), bool), "Unknowns need a question and explicit blocking impact.")
        require(unknown.get("status", "OPEN") in {"OPEN", "RESOLVED"}, "Invalid unknown state.")
        require(unknown.get("status") != "RESOLVED" or unknown.get("evidence"), "Resolved unknowns need evidence.")
    milestones = indexed(work.get("milestones"), "milestone")
    tasks = indexed(work.get("tasks"), "task")
    require(milestones and tasks, "Work needs coherent milestones and executable tasks.")
    dependency_graph(milestones, "milestone")
    dependency_graph(tasks, "task")
    all_checks: set[str] = set()
    check_milestones = {}
    for key, task in tasks.items():
        require(task.get("milestone") in milestones and task.get("title"), f"{key} needs a milestone and title.")
        require(task.get("status", "PENDING") in TASK_STATES, f"{key} has an invalid task status.")
        require(isinstance(task.get("requirement_ids"), list) and task["requirement_ids"] and set(task["requirement_ids"]) <= set(reqs), f"{key} must trace to declared requirements.")
        require(set(task.get("decision_ids", [])) <= set(decisions), f"{key} references an unknown architecture decision.")
        require(isinstance(task.get("paths"), list) and task["paths"], f"{key} needs relevant repository paths for staleness checks.")
        for path in task["paths"]:
            relative_path(path)
        checks = indexed(task.get("checks"), f"{key} check")
        require(checks and not (set(checks) & all_checks), "Verification check IDs must be globally unique and nonempty.")
        all_checks.update(checks)
        check_milestones.update({check_id: task["milestone"] for check_id in checks})
        for check_id, check in checks.items():
            require(check.get("kind") in {"command", "review"}, f"{check_id} must be command or explicit semantic review.")
            if check["kind"] == "command":
                argv = check.get("argv")
                require(isinstance(argv, list) and argv and all(isinstance(s, str) and s for s in argv), f"{check_id} requires an argument array, never implicit shell interpolation.")
                require(isinstance(check.get("timeout", 120), int) and 1 <= check.get("timeout", 120) <= 600, f"{check_id} timeout must be 1–600 seconds.")
        criteria(task.get("done_when"), set(checks), key)
    for key, milestone in milestones.items():
        require(milestone.get("title") and any(t["milestone"] == key for t in tasks.values()), f"{key} needs a title and meaningful work.")
        criteria(milestone.get("done_when"), all_checks, key)
        require(set(milestone.get("invariant_ids", [])) <= set(invariants), f"{key} references unknown architecture invariants.")
        ancestors = set(milestone.get("depends_on", []))
        while True:
            expanded = ancestors | {parent for mid in ancestors for parent in milestones[mid].get("depends_on", [])}
            if expanded == ancestors:
                break
            ancestors = expanded
        require(all(check_milestones[cid] in ancestors | {key} for criterion in milestone["done_when"] for cid in criterion["check_ids"]),
                f"{key} cannot require verification from a future/unrelated milestone.", "BLOCKED_DEPENDENCY")
    combined = {"m-" + key: {"depends_on": ["t-" + t["id"] for t in tasks.values() if t["milestone"] == key]}
                for key in milestones}
    combined.update({"t-" + key: {"depends_on": ["t-" + parent for parent in task.get("depends_on", [])] +
                    ["m-" + parent for parent in milestones[task["milestone"]].get("depends_on", [])]}
                     for key, task in tasks.items()})
    dependency_graph(combined, "combined task/milestone")
    criteria(work.get("done_when"), all_checks, "Project")
    return copy.deepcopy(models)


def validate_models(models: Any) -> dict:
    try:
        return _validate_models(models)
    except EngineeringError:
        raise
    except (TypeError, KeyError, AttributeError, RecursionError):
        raise EngineeringError("SPECIFICATION_INVALID", "Malformed engineering model field types or references.") from None
