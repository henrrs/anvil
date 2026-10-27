"""Cheap activation signals and bounded source inventory, not semantic guessing."""

from __future__ import annotations

import os
from pathlib import Path

from .contracts import require
from .repository import specification


def assess(request: str, signals: dict | None = None) -> dict:
    signals = signals or {}
    names = [key for key in ("architecture_change", "migration", "schema_change", "distributed_behavior", "cross_component") if signals.get(key) is True]
    for key, threshold in (("requirements", 8), ("subsystems", 3), ("files", 8), ("milestones", 2), ("acceptance_criteria", 5)):
        value = signals.get(key, 0)
        require(isinstance(value, int) and value >= 0, f"Complexity signal {key} must be a non-negative integer.")
        if value >= threshold:
            names.append(key)
    if len(request) > 6000:
        names.append("specification_length")
    disabled = os.environ.get("ANVIL_ENGINEERING", "auto") == "off"
    return {"workflow": "DIRECT" if disabled or not names else "LONG_HORIZON", "signals": names,
            "state_created": False, "disabled": disabled,
            "note": "Signals guide activation; semantic scope may escalate or de-escalate without restarting the task."}


def analyze(path: Path) -> dict:
    source = specification(path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    headings = [{"line": n, "heading": line.strip()[:180]} for n, line in enumerate(lines, 1) if line.startswith("#")]
    return {"source": source, "lines": len(lines), "headings": headings[:80], "headings_omitted": max(0, len(headings) - 80),
            "status": "SEMANTIC_ANALYSIS_REQUIRED",
            "next": "Normalize objective, requirements/provenance, constraints, acceptance, architecture, risks, unknowns and deferred scope; do not infer them from headings alone."}
