"""Bounded recovery packets reconstructed without conversational history."""

from __future__ import annotations

import json
from pathlib import Path

from . import engine
from .contracts import indexed, require


def resume(state: dict, root: Path, task_id: str | None = None, max_bytes: int = 24000) -> dict:
    drift = engine.current_drift(state, root)
    if drift["stale"]:
        affected = {t["id"] for t in engine.tasks(state).values()} if drift["specification_changed"] else set()
        engine._invalidate(state, set(drift["changed_files"]), affected)
    engine.refresh(state)
    tasks = engine.tasks(state)
    work = state["models"]["work"]
    milestones = indexed(work["milestones"], "milestone")
    active = next((t for t in tasks.values() if t["status"] == "ACTIVE"), None)
    ready = [t for t in tasks.values() if t["status"] in {"PENDING", "IMPLEMENTED"}
             and all(tasks[d]["status"] == "VERIFIED" for d in t.get("depends_on", []))
             and all(milestones[d]["status"] == "COMPLETE" for d in milestones[t["milestone"]].get("depends_on", []))]
    selected = tasks.get(task_id) if task_id else active or next(iter(ready), None)
    require(not task_id or selected, "Unknown context task.")
    relevant_ids = set(selected["requirement_ids"]) if selected else set()
    decision_ids = set(selected.get("decision_ids", [])) if selected else set()
    architecture = state["models"]["architecture"]
    completed = [t["id"] for t in tasks.values() if t["status"] == "VERIFIED"]
    coverage = engine.coverage(state)
    coverage["unverified_required_omitted"] = max(0, len(coverage["unverified_required"]) - 20)
    coverage["unverified_required"] = coverage["unverified_required"][:20]
    if drift["stale"]:
        next_action = "Review changed files/specification and revalidate or replan; do not trust affected verification or rerun work blindly."
    elif active:
        next_action = f"Inspect partial effects of {active['id']}; reconcile before executing or restarting that unit."
    elif selected and selected["status"] == "IMPLEMENTED":
        next_action = f"Run missing checks/reviews for {selected['id']}, then checkpoint architecture."
    elif selected:
        next_action = f"Start {selected['id']} after validating its assumptions."
    else:
        next_action = "Evaluate project completion gates; resolve remaining blockers or finish."
    completion = engine.completion(state)
    if drift["stale"]:
        completion["ready"] = False
        completion["blockers"].append("Repository/specification anchor must be revalidated before completion.")
    packet = {"id": state["id"], "revision": state["revision"], "status": "WORK_STATE_STALE" if drift["stale"] else state["status"],
              "objective": state["models"]["requirements"]["objective"],
              "architecture": {"principles": architecture.get("principles", []), "boundaries": architecture.get("boundaries", []),
                               "invariants": [{k: i[k] for k in ("id", "statement", "kind")} for i in architecture.get("invariants", [])],
                               "decisions": [d for d in architecture.get("decisions", []) if not selected or d["id"] in decision_ids]},
              "requirements": [r for r in state["models"]["requirements"]["items"] if r["id"] in relevant_ids],
              "current_milestone": milestones.get(selected["milestone"]) if selected else None,
              "current_task": selected, "completed_tasks": completed[:20], "completed_tasks_total": len(completed),
              "completed_tasks_omitted": max(0, len(completed) - 20),
              "blockers": [{"task_id": t["id"], "reason": t.get("blocker", "Unresolved dependency or scope")} for t in tasks.values() if t["status"] in {"BLOCKED", "DEFERRED"}],
              "unknowns": [u for u in architecture.get("unknowns", []) if u.get("status", "OPEN") != "RESOLVED"],
              "coverage": coverage, "architecture_conformance": engine.conformance(state),
              "architecture_findings": [{"id": item["invariant_id"], "result": item["result"],
                                         "findings": item.get("findings", [item.get("summary", "")])[:5]}
                                        for item in state["verification"] if item.get("invariant_id") and item["valid"] and item["result"] != "PASS"][:10],
              "verification": [{k: v[k] for k in ("id", "result", "valid", "kind")}
                               for v in state["verification"] if selected and v.get("task_id") == selected["id"]],
              "drift": {k: v for k, v in drift.items() if k != "current"},
              "recent_failures": state["failures"][-3:], "next_action": next_action,
              "completion": completion, "counters": state.get("counters", {}),
              "scope": "Current unit only; load named requirement sources, decisions and implementation files on demand. No work was executed."}
    require(len(json.dumps(packet, ensure_ascii=False).encode()) <= max_bytes,
            "Resume packet exceeds its context budget; narrow models or select a work unit with --task.", "CONTEXT_LIMIT")
    return packet
