"""Task-local expansion hints and bounded source inventory, not semantic guessing."""

from __future__ import annotations

import os
from pathlib import Path

from .contracts import require
from .repository import specification


_TASK_EXPANSION_SIGNALS = {
    "architecture_change": "architecture boundary",
    "public_contract_change": "public contract",
    "dependency_direction_change": "dependency direction",
    "state_ownership_change": "state ownership",
    "runtime_boundary_change": "runtime boundary",
    "failure_semantics_change": "failure semantics",
    "persistence_change": "persistent state",
    "migration": "migration",
    "schema_change": "schema compatibility",
    "distributed_behavior": "distributed behavior",
    "multiple_dependent_changes": "dependent changes",
    "next_action_unclear": "unresolved next action",
    "resume_long_horizon": "explicit long-horizon continuation",
    "user_requests_deep_review": "explicit deep-review request",
}
_PROJECT_CONTEXT_SIGNALS = {"requirements", "subsystems", "files", "milestones", "acceptance_criteria", "cross_component"}


def assess(request: str, signals: dict | None = None) -> dict:
    signals = signals or {}
    require(isinstance(request, str), "Request must be text.")
    require(isinstance(signals, dict), "Signals must be a JSON object.")
    names = []
    for key, description in _TASK_EXPANSION_SIGNALS.items():
        if key not in signals:
            continue
        require(type(signals[key]) is bool, f"Task signal {key} must be true or false.")
        if signals[key]:
            names.append(description)
    context = []
    for key in sorted(_PROJECT_CONTEXT_SIGNALS):
        if key not in signals:
            continue
        value = signals[key]
        if key == "cross_component":
            require(type(value) is bool, "Project-context signal cross_component must be true or false.")
            present = value
        else:
            require(type(value) is int and value >= 0, f"Project-context signal {key} must be a non-negative integer.")
            present = value > 0
        if present:
            context.append(key)
    if len(request) > 6000:
        context.append("long_request_text")
    disabled = os.environ.get("ANVIL_ENGINEERING", "auto") == "off"
    expand = bool(names) and not disabled
    return {"workflow": "EXPAND" if expand else "DIRECT", "signals": names, "project_context": context,
            "state_created": False, "disabled": disabled, "judgment": "MODEL_REQUIRED",
            "note": "Assess the requested change, not repository size or request length. EXPAND means choose only the relevant evidence/model/domain branch; it does not itself require a plan or task store. Retain evidence and narrow again when the risk is resolved."}


def analyze(path: Path) -> dict:
    source = specification(path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    headings = [{"line": n, "heading": line.strip()[:180]} for n, line in enumerate(lines, 1) if line.startswith("#")]
    return {"source": source, "lines": len(lines), "headings": headings[:80], "headings_omitted": max(0, len(headings) - 80),
            "status": "SEMANTIC_ANALYSIS_REQUIRED",
            "next": "Normalize objective, requirements/provenance, constraints, acceptance, architecture, risks, unknowns and deferred scope; do not infer them from headings alone."}
