"""Engineering transitions, traceability and completion gates, independent of models/runtimes."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import invariants, repository, verification
from .contracts import indexed, require, validate_models
from .errors import EngineeringError


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def event(state: dict, action: str, **details: object) -> None:
    state["events"].append({"at": datetime.now(timezone.utc).isoformat(), "action": action, **details})
    state["events"] = state["events"][-100:]
    counters = state.setdefault("counters", {})
    counters[action] = counters.get(action, 0) + 1


def create(task_id: str, root: Path, spec: Path, models: dict) -> dict:
    require(os.environ.get("ANVIL_ENGINEERING", "auto") != "off", "Engineering state is disabled for this run.", "FEATURE_DISABLED")
    normalized = validate_models(models)
    for requirement in normalized["requirements"]["items"]:
        require(requirement.get("status", "PENDING") in {"PENDING", "DEFERRED", "NOT_APPLICABLE"},
                "Imported requirements cannot claim implementation or verification.")
        requirement.setdefault("status", "PENDING")
    for task in normalized["work"]["tasks"]:
        require(task.get("status", "PENDING") == "PENDING", "Imported tasks must start pending; reconcile implementation explicitly.")
        task["status"] = "PENDING"
        task.pop("implemented_by", None)
        task.pop("blocker", None)
    state = {"schema_version": 1, "id": task_id, "revision": 0, "status": "ACTIVE", "models": normalized,
             "anchor": repository.observe(root, normalized, spec), "verification": [], "events": [],
             "failures": [], "counters": {}, "recovery_required": False}
    event(state, "created")
    refresh(state)
    return state


def tasks(state: dict) -> dict:
    return indexed(state["models"]["work"]["tasks"], "task")


def latest(state: dict, *, check_id: str | None = None, invariant_id: str | None = None) -> dict | None:
    for item in reversed(state["verification"]):
        if (check_id and item.get("check_id") == check_id) or (invariant_id and item.get("invariant_id") == invariant_id):
            return item
    return None


def passed(state: dict, check_id: str) -> bool:
    item = latest(state, check_id=check_id)
    owner = next((task for task in tasks(state).values() if any(c["id"] == check_id for c in task["checks"])), None)
    definition = next((c for c in owner["checks"] if c["id"] == check_id), None) if owner else None
    return bool(item and owner and item.get("task_id") == owner["id"] and
                item.get("definition_sha256") == fingerprint(definition) and item["result"] == "PASS" and item["valid"])


def criteria_pass(state: dict, items: list[dict]) -> bool:
    return all(passed(state, key) for item in items for key in item["check_ids"])


def conformance(state: dict) -> dict:
    result = {}
    for invariant in state["models"]["architecture"].get("invariants", []):
        item = latest(state, invariant_id=invariant["id"])
        result[invariant["id"]] = item["result"] if item and item["valid"] else "UNKNOWN"
    return result


def refresh(state: dict) -> None:
    work = state["models"]["work"]
    items = tasks(state)
    for task in items.values():
        if task["status"] in {"IMPLEMENTED", "VERIFIED"}:
            task["status"] = "VERIFIED" if all(passed(state, check["id"]) for check in task["checks"]) and criteria_pass(state, task["done_when"]) else "IMPLEMENTED"
    for requirement in state["models"]["requirements"]["items"]:
        if requirement["status"] in {"DEFERRED", "NOT_APPLICABLE"}:
            continue
        linked = [task for task in items.values() if requirement["id"] in task["requirement_ids"]]
        states = {task["status"] for task in linked}
        requirement["status"] = ("VERIFIED" if linked and states == {"VERIFIED"} else
                                 "IMPLEMENTED" if linked and states <= {"VERIFIED", "IMPLEMENTED"} else
                                 "BLOCKED" if "BLOCKED" in states else
                                 "IN_PROGRESS" if states & {"ACTIVE", "IMPLEMENTED", "VERIFIED"} else "PENDING")
        requirement["implemented_by"] = sorted({path for task in linked for path in task.get("implemented_by", [])})
        requirement["verified_by"] = [item["id"] for item in state["verification"]
                                      if item.get("task_id") in {task["id"] for task in linked} and item["valid"] and item["result"] == "PASS"]
    for milestone in work["milestones"]:
        linked = [task for task in items.values() if task["milestone"] == milestone["id"]]
        statuses = {task["status"] for task in linked}
        architecture_pass = all(conformance(state).get(key) == "PASS" for key in milestone.get("invariant_ids", []))
        milestone["status"] = ("COMPLETE" if statuses == {"VERIFIED"} and criteria_pass(state, milestone["done_when"]) and architecture_pass else
                               "BLOCKED" if "BLOCKED" in statuses else
                               "ACTIVE" if statuses - {"PENDING"} else "PENDING")
    active = next((task for task in items.values() if task["status"] == "ACTIVE"), None)
    work["current_task"] = active["id"] if active else None
    work["current_milestone"] = active["milestone"] if active else next((m["id"] for m in work["milestones"] if m["status"] != "COMPLETE"), None)
    if state["status"] == "COMPLETE" and not completion(state)["ready"]:
        state["status"] = "ACTIVE"


def coverage(state: dict) -> dict:
    counts = {status: 0 for status in ("PENDING", "IN_PROGRESS", "IMPLEMENTED", "VERIFIED", "BLOCKED", "DEFERRED", "NOT_APPLICABLE")}
    for item in state["models"]["requirements"]["items"]:
        counts[item["status"]] += 1
    return {"total": sum(counts.values()), "counts": counts,
            "unverified_required": [r["id"] for r in state["models"]["requirements"]["items"]
                                    if r["priority"] == "required" and r["status"] not in {"VERIFIED", "NOT_APPLICABLE"}]}


def completion(state: dict) -> dict:
    work = state["models"]["work"]
    blockers = []
    if coverage(state)["unverified_required"]:
        blockers.append("Required requirements remain unverified (including required deferred scope).")
    if any(m.get("status") != "COMPLETE" for m in work["milestones"]):
        blockers.append("Milestone definitions of done remain unmet.")
    if not criteria_pass(state, work["done_when"]):
        blockers.append("Project verification criteria remain unmet.")
    if any(result != "PASS" for result in conformance(state).values()):
        blockers.append("Architecture invariants need successful checkpoints/reviews.")
    if any(u.get("blocking") and u.get("status", "OPEN") != "RESOLVED" for u in state["models"]["architecture"].get("unknowns", [])):
        blockers.append("Required architectural unknowns remain unresolved.")
    if any(d.get("needs_review") for d in state["models"]["architecture"].get("decisions", [])):
        blockers.append("Changed evidence requires architecture decision review/replanning.")
    if state.get("recovery_required"):
        blockers.append("Recovered state must be revalidated.")
    return {"ready": not blockers, "blockers": blockers}


def current_drift(state: dict, root: Path) -> dict:
    return repository.drift(state["anchor"], root, state["models"])


def require_current(state: dict, root: Path) -> None:
    require(not current_drift(state, root)["stale"], "Repository/specification evidence changed; previous assumptions require review.", "WORK_STATE_STALE")
    require(state["status"] != "ARCHIVED", "Archived work is read-only.", "WORK_STATE_ARCHIVED")


def start(state: dict, root: Path, task_id: str) -> None:
    require_current(state, root)
    items = tasks(state)
    require(task_id in items, "Unknown work task.")
    task = items[task_id]
    require(task["status"] in {"PENDING", "BLOCKED"}, "Only pending/blocked tasks can start; inspect interrupted active work before reconciling it.")
    milestones = indexed(state["models"]["work"]["milestones"], "milestone")
    require(all(items[key]["status"] == "VERIFIED" for key in task.get("depends_on", [])) and
            all(milestones[key]["status"] == "COMPLETE" for key in milestones[task["milestone"]].get("depends_on", [])),
            "Task or milestone dependencies are not verified.", "BLOCKED_DEPENDENCY")
    require(not any(t["status"] == "ACTIVE" for t in items.values()), "Reconcile the current active work unit before starting another.")
    task["status"] = "ACTIVE"
    task.pop("blocker", None)
    event(state, "started", task_id=task_id)
    refresh(state)


def _invalidate(state: dict, changed: set[str], affected_tasks: set[str] | None = None) -> set[str]:
    affected = set(affected_tasks or [])
    items = tasks(state)
    for task in items.values():
        if changed & set(task["paths"]):
            affected.add(task["id"])
    while True:
        affected_milestones = {items[key]["milestone"] for key in affected}
        dependent_milestones = {m["id"] for m in state["models"]["work"]["milestones"]
                                if set(m.get("depends_on", [])) & affected_milestones}
        expanded = affected | {t["id"] for t in items.values() if set(t.get("depends_on", [])) & affected
                               or t["milestone"] in dependent_milestones}
        if expanded == affected:
            break
        affected = expanded
    for item in state["verification"]:
        if changed & set(item.get("files", {})) or item.get("task_id") in affected or (changed and item.get("invariant_id")):
            item["valid"] = False
    for task_id in affected:
        if items[task_id]["status"] == "VERIFIED":
            items[task_id]["status"] = "IMPLEMENTED"
    return affected


def implement(state: dict, root: Path, task_id: str, files: list[str]) -> None:
    items = tasks(state)
    require(task_id in items, "Unknown work task.")
    task = items[task_id]
    require(task["status"] in {"ACTIVE", "IMPLEMENTED"}, "Start or reconcile the task before recording implementation.")
    require(files and set(files) <= set(task["paths"]), "Implementation paths must belong to this planned work unit.")
    require(all(value is not None for value in repository.hashes(root, files).values()), "Implemented files must exist.")
    changes = current_drift(state, root)
    require(not changes["specification_changed"] and not changes["git_changes"] and set(changes["changed_files"]) <= set(task["paths"]),
            "Changes outside this work unit require revalidation/replanning.", "WORK_STATE_STALE")
    _invalidate(state, set(changes["changed_files"]))
    state["anchor"] = changes["current"]
    task["implemented_by"] = sorted(set(task.get("implemented_by", [])) | set(files))
    task["status"] = "IMPLEMENTED"
    event(state, "implemented", task_id=task_id, files=files)
    refresh(state)


def _append_record(state: dict, record: dict) -> None:
    record.update(id=f"V{state.setdefault('evidence_sequence', 0) + 1}", valid=True,
                  at=datetime.now(timezone.utc).isoformat())
    state["evidence_sequence"] = state.get("evidence_sequence", 0) + 1
    # Keep the latest result for each check/invariant plus a bounded audit trail in events.
    state["verification"] = [r for r in state["verification"]
                             if not (record.get("check_id") and r.get("check_id") == record["check_id"])
                             and not (record.get("invariant_id") and r.get("invariant_id") == record["invariant_id"])
                             and not (record.get("decision_id") and r.get("decision_id") == record["decision_id"])]
    state["verification"].append(record)


def check(state: dict, root: Path, task_id: str, check_id: str, hypothesis: str = "") -> dict:
    require_current(state, root)
    task = tasks(state).get(task_id)
    require(task and task["status"] in {"IMPLEMENTED", "VERIFIED"}, "Record implementation before verification.")
    definition = next((c for c in task["checks"] if c["id"] == check_id), None)
    require(definition and definition["kind"] == "command", "Select a declared command check; semantic checks require review.")
    before = repository.hashes(root, task["paths"])
    action = fingerprint({"argv": definition["argv"], "files": before, "hypothesis": hypothesis})
    require(not any(f["fingerprint"] == action for f in state["failures"]),
            "An equivalent failed check has no changed evidence or hypothesis.", "REPEATED_FAILED_ACTION")
    result = verification.run(definition["argv"], root, definition.get("timeout", 120))
    after = repository.hashes(root, task["paths"])
    if before != after:
        result.update(result="FAIL", reason="CHECK_CHANGED_IMPLEMENTATION")
    record = {**result, "task_id": task_id, "check_id": check_id, "kind": "command", "confidence": "OBSERVED",
              "files": after, "definition_sha256": fingerprint(definition)}
    _append_record(state, record)
    if result["result"] != "PASS":
        state["failures"].append({"fingerprint": action, "task_id": task_id, "check_id": check_id,
                                  "hypothesis": hypothesis[:500], "reason": result.get("reason") or "NONZERO_EXIT"})
        state["failures"] = state["failures"][-40:]
    event(state, "verification", task_id=task_id, check_id=check_id, result=result["result"])
    refresh(state)
    return record


def review(state: dict, root: Path, target_id: str, result: str, summary: str, observer: str) -> dict:
    require_current(state, root)
    require(result in {"PASS", "FAIL", "UNKNOWN"} and summary and len(summary) <= 800 and observer in {"human", "model"}, "Semantic reviews need an explicit result, concise evidence rationale and observer.")
    for task in tasks(state).values():
        definition = next((c for c in task["checks"] if c["id"] == target_id and c["kind"] == "review"), None)
        if definition:
            require(task["status"] in {"IMPLEMENTED", "VERIFIED"}, "Implement before reviewing.")
            record = {"task_id": task["id"], "check_id": target_id, "files": repository.hashes(root, task["paths"]),
                      "definition_sha256": fingerprint(definition)}
            break
    else:
        invariant = next((i for i in state["models"]["architecture"].get("invariants", []) if i["id"] == target_id and i["kind"] == "semantic"), None)
        decision = next((d for d in state["models"]["architecture"].get("decisions", []) if d["id"] == target_id), None)
        require(invariant or decision, "Select a declared semantic check, invariant or architecture decision.")
        if invariant:
            record = {"invariant_id": target_id, "files": repository.hashes(root, invariants.scope(root, invariant["paths"]))}
        else:
            record = {"decision_id": target_id, "files": repository.hashes(root, decision.get("paths", []))}
    require(record["files"] and all(record["files"].values()), "Semantic review requires existing evidence files.")
    if record.get("decision_id"):
        decision["needs_review"] = result != "PASS"
    record.update(kind="semantic_review", result=result, confidence="SUPPORTED" if result == "PASS" else "UNKNOWN", summary=summary, observer=observer)
    _append_record(state, record)
    event(state, "reviewed", target_id=target_id, result=result, observer=observer)
    refresh(state)
    return record


def checkpoint(state: dict, root: Path) -> dict:
    require_current(state, root)
    for invariant in state["models"]["architecture"].get("invariants", []):
        if invariant["kind"] == "semantic":
            continue
        record = invariants.evaluate(root, invariant)
        _append_record(state, record)
    result = conformance(state)
    event(state, "architecture_checkpoint", results=result)
    refresh(state)
    return result


def revalidate(state: dict, root: Path, reason: str) -> dict:
    require(reason, "Revalidation needs the observed change or inspection rationale.")
    changes = current_drift(state, root)
    require(not changes["specification_changed"], "Specification changed; normalize affected requirements and replan before continuing.", "REQUIREMENT_CONFLICT")
    affected = _invalidate(state, set(changes["changed_files"]))
    for decision in state["models"]["architecture"].get("decisions", []):
        if set(decision.get("paths", [])) & set(changes["changed_files"]):
            decision["needs_review"] = True
    state["anchor"] = changes["current"]
    state["recovery_required"] = False
    event(state, "revalidated", affected_tasks=sorted(affected), reason=reason[:500])
    refresh(state)
    return {"affected_tasks": sorted(affected), "changed_files": changes["changed_files"]}


def reconcile(state: dict, root: Path, task_id: str, outcome: str, reason: str) -> None:
    task = tasks(state).get(task_id)
    require(task and task["status"] == "ACTIVE" and outcome in {"PENDING", "IMPLEMENTED", "BLOCKED"} and reason,
            "Reconcile only interrupted active work after inspecting its partial effects.")
    revalidate(state, root, reason)
    task["status"] = outcome
    if outcome == "IMPLEMENTED":
        require(all(repository.hashes(root, task["paths"]).values()), "Partial implementation files are missing.")
        task["implemented_by"] = task["paths"][:]
    if outcome == "BLOCKED":
        task["blocker"] = reason[:500]
    event(state, "reconciled", task_id=task_id, outcome=outcome, reason=reason[:500])
    refresh(state)


def replan(state: dict, root: Path, spec: Path, models: dict, reason: str, scope_authorization: str = "") -> None:
    require(reason, "Replanning needs changed evidence and a concise rationale.")
    proposed = validate_models(models)
    old = state["models"]
    old_tasks = tasks(state)
    old_reqs = indexed(old["requirements"]["items"], "requirement")
    new_reqs = indexed(proposed["requirements"]["items"], "requirement")
    reduced_scope = [key for key, previous in old_reqs.items() if previous["priority"] == "required" and
                     (key not in new_reqs or new_reqs[key]["priority"] != "required" or
                      (new_reqs[key].get("status") in {"DEFERRED", "NOT_APPLICABLE"} and previous.get("status") != new_reqs[key].get("status")))]
    require(not reduced_scope or scope_authorization, "Reducing required scope needs an explicit user-authorization reference.", "REQUIREMENT_CONFLICT")
    old_decisions = indexed(old["architecture"].get("decisions", []), "decision")
    changed_requirements = {r["id"] for r in proposed["requirements"]["items"]
                            if {k: v for k, v in r.items() if k not in {"status", "implemented_by", "verified_by"}} !=
                            {k: v for k, v in old_reqs.get(r["id"], {}).items() if k not in {"status", "implemented_by", "verified_by"}}}
    changed_decisions = {d["id"] for d in proposed["architecture"].get("decisions", [])
                         if {k: v for k, v in d.items() if k != "needs_review"} !=
                         {k: v for k, v in old_decisions.get(d["id"], {}).items() if k != "needs_review"}}
    for decision in proposed["architecture"].get("decisions", []):
        if decision["id"] not in changed_decisions and old_decisions.get(decision["id"], {}).get("needs_review"):
            decision["needs_review"] = True
    affected = set()
    for task in proposed["work"]["tasks"]:
        previous = old_tasks.get(task["id"], {})
        runtime_keys = {"status", "implemented_by", "blocker"}
        changed = ({k: v for k, v in task.items() if k not in runtime_keys} != {k: v for k, v in previous.items() if k not in runtime_keys}
                   or set(task["requirement_ids"]) & changed_requirements or set(task.get("decision_ids", [])) & changed_decisions)
        task["status"] = previous.get("status", "PENDING")
        task.pop("implemented_by", None)
        task.pop("blocker", None)
        if previous.get("implemented_by"):
            task["implemented_by"] = previous["implemented_by"]
        if changed:
            affected.add(task["id"])
            if task["status"] == "VERIFIED":
                task["status"] = "IMPLEMENTED"
    # A new spec hash alone is not permission to invent VERIFIED requirements.
    for req in proposed["requirements"]["items"]:
        if req.get("status") not in {"DEFERRED", "NOT_APPLICABLE"}:
            req["status"] = "PENDING"
    changed_invariants = old["architecture"].get("invariants", []) != proposed["architecture"].get("invariants", [])
    state["models"] = proposed
    new_anchor = repository.observe(root, proposed, spec)
    changed_files = {p for p in set(state["anchor"]["files"]) | set(new_anchor["files"])
                     if state["anchor"]["files"].get(p) != new_anchor["files"].get(p)}
    affected = _invalidate(state, changed_files, affected)
    if changed_invariants:
        for item in state["verification"]:
            if item.get("invariant_id"):
                item["valid"] = False
    state["anchor"] = new_anchor
    state["status"] = "ACTIVE"
    event(state, "replanned", reason=reason[:500], affected_tasks=sorted(affected),
          changed_requirements=sorted(changed_requirements), changed_decisions=sorted(changed_decisions),
          reduced_scope=reduced_scope, scope_authorization=scope_authorization[:500])
    refresh(state)


def finish(state: dict, root: Path) -> None:
    require_current(state, root)
    refresh(state)
    result = completion(state)
    require(result["ready"], " ".join(result["blockers"]), "VERIFICATION_FAILED")
    state["status"] = "COMPLETE"
    event(state, "completed")
