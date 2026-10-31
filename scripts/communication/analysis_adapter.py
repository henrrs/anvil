"""Communication-side adapter for renderer-independent analytical findings."""

from __future__ import annotations

from typing import Any

from .contracts import validate_evidence as validate_artifact_evidence
from .contracts import validate_finding as validate_artifact_finding

from analysis.findings import validate_result


def artifact_components(raw_result: Any) -> dict[str, Any]:
    """Return existing artifact evidence/findings fields without choosing layout."""
    result = validate_result(raw_result)
    evidence = []
    for item in result["evidence"]:
        mapped = {key: item[key] for key in ("id", "claim", "epistemic", "confidence", "source")}
        for key in ("method", "calculation", "data"):
            if key in item:
                mapped[key] = item[key]
        evidence.append(validate_artifact_evidence(mapped))
    findings = []
    for item in result["findings"]:
        mapped = {
            "id": item["id"], "claim": item["statement"], "epistemic": item["type"],
            "confidence": item["confidence"], "evidence_ids": item["evidence_ids"],
            "materiality": item["materiality"]["overall"].casefold(),
            "limitations": item["caveats"], "alternative_explanations": item["alternatives"],
        }
        findings.append(validate_artifact_finding(mapped))
    return {"evidence": evidence, "findings": findings,
            "finding_order": [identifier for tier in result["materiality_tiers"] for identifier in tier],
            "narrative": result["narrative"]}
