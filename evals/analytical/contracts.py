"""Versioned contracts and failure taxonomy for analytical evaluations.

This module belongs to the evaluator package only. Production analysis must not
import it or any fixture/ground-truth file.
"""

from __future__ import annotations

from typing import Any


FAILURE_CLASSES = frozenset({
    "NUMERICAL", "GRAIN", "ENTITY_RESOLUTION", "SEMANTIC", "POPULATION",
    "COHORT", "COMPOSITION", "DISTRIBUTION", "DISCOVERY", "INVESTIGATION",
    "CONTRIBUTION", "MATERIALITY", "CLAIM_SUPPORT", "CLAIM_CALIBRATION",
    "COMMUNICATION", "PERFORMANCE", "INFRASTRUCTURE",
})

MATERIALITY = frozenset({"HIGH", "MEDIUM", "LOW", "UNKNOWN"})
CLAIM_STRENGTH = frozenset({"OBSERVED", "DERIVED", "SUPPORTED", "INFERRED", "HYPOTHESIS", "UNKNOWN"})
SURFACES = frozenset({"direct", "report", "presentation"})


class EvaluationContractError(ValueError):
    """A persisted or model-produced evaluation object violates its schema."""


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvaluationContractError(f"{label} must be an object")
    return value


def _text(value: Any, label: str, maximum: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise EvaluationContractError(f"{label} must be non-empty text of at most {maximum} characters")
    return value.strip()


def _text_list(value: Any, label: str, *, count: int = 40, size: int = 1000) -> list[str]:
    if not isinstance(value, list) or len(value) > count:
        raise EvaluationContractError(f"{label} must be a list with at most {count} entries")
    return [_text(item, f"{label}[{index}]", size) for index, item in enumerate(value)]


def validate_candidate(raw: Any) -> dict[str, Any]:
    """Validate observable analytical output; no chain-of-thought field is accepted."""
    value = _object(raw, "candidate")
    allowed = {"schema_version", "summary", "semantics", "questions", "facts", "findings", "claims", "surfaces", "limitations"}
    if set(value) - allowed or value.get("schema_version") != 1:
        raise EvaluationContractError("candidate has unsupported fields or schema_version")
    semantics_raw = _object(value.get("semantics", {}), "semantics")
    if set(semantics_raw) - {"observation_grain", "entity_fields", "time_fields", "measure_fields"}:
        raise EvaluationContractError("semantics contains unsupported fields")
    semantics = {key: _text_list(semantics_raw.get(key, []), f"semantics.{key}", count=20, size=240)
                 for key in ("observation_grain", "entity_fields", "time_fields", "measure_fields")}

    facts_raw = value.get("facts", [])
    if not isinstance(facts_raw, list) or len(facts_raw) > 100:
        raise EvaluationContractError("facts must contain at most 100 entries")
    facts: list[dict[str, Any]] = []
    fact_ids: set[str] = set()
    for index, item in enumerate(facts_raw):
        entry = _object(item, f"facts[{index}]")
        if set(entry) - {"id", "statement", "value", "unit", "evidence_columns"}:
            raise EvaluationContractError(f"facts[{index}] contains unsupported fields")
        identifier = _text(entry.get("id"), f"facts[{index}].id", 64)
        if identifier in fact_ids:
            raise EvaluationContractError(f"duplicate fact id {identifier!r}")
        fact_ids.add(identifier)
        facts.append({"id": identifier, "statement": _text(entry.get("statement"), f"facts[{index}].statement"),
                      "value": entry.get("value"), "unit": _text(entry.get("unit", "unknown"), f"facts[{index}].unit", 80),
                      "evidence_columns": _text_list(entry.get("evidence_columns", []), f"facts[{index}].evidence_columns", count=20, size=240)})

    findings_raw = value.get("findings", [])
    if not isinstance(findings_raw, list) or len(findings_raw) > 100:
        raise EvaluationContractError("findings must contain at most 100 entries")
    findings: list[dict[str, Any]] = []
    for index, item in enumerate(findings_raw):
        entry = _object(item, f"findings[{index}]")
        if set(entry) - {"statement", "materiality", "confidence", "evidence_fact_ids", "evidence_columns"}:
            raise EvaluationContractError(f"findings[{index}] contains unsupported fields")
        if entry.get("materiality") not in MATERIALITY or entry.get("confidence") not in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
            raise EvaluationContractError(f"findings[{index}] has unsupported materiality or confidence")
        refs = _text_list(entry.get("evidence_fact_ids", []), f"findings[{index}].evidence_fact_ids", count=30, size=64)
        findings.append({"statement": _text(entry.get("statement"), f"findings[{index}].statement"),
                         "materiality": entry["materiality"], "confidence": entry["confidence"],
                         "evidence_fact_ids": refs,
                         "evidence_columns": _text_list(entry.get("evidence_columns", []), f"findings[{index}].evidence_columns", count=30, size=240)})

    claims_raw = value.get("claims", [])
    if not isinstance(claims_raw, list) or len(claims_raw) > 150:
        raise EvaluationContractError("claims must contain at most 150 entries")
    claims = []
    for index, item in enumerate(claims_raw):
        entry = _object(item, f"claims[{index}]")
        if set(entry) - {"text", "evidence_fact_ids", "strength", "material"}:
            raise EvaluationContractError(f"claims[{index}] contains unsupported fields")
        if entry.get("strength") not in CLAIM_STRENGTH or not isinstance(entry.get("material", True), bool):
            raise EvaluationContractError(f"claims[{index}] has unsupported strength or material flag")
        claims.append({"text": _text(entry.get("text"), f"claims[{index}].text"),
                       "evidence_fact_ids": _text_list(entry.get("evidence_fact_ids", []), f"claims[{index}].evidence_fact_ids", count=30, size=64),
                       "strength": entry["strength"], "material": entry.get("material", True)})

    surfaces_raw = _object(value.get("surfaces", {}), "surfaces")
    if set(surfaces_raw) - SURFACES:
        raise EvaluationContractError("surfaces contains unsupported output types")
    surfaces: dict[str, list[dict[str, Any]]] = {}
    for surface in SURFACES:
        entries = surfaces_raw.get(surface, [])
        if not isinstance(entries, list) or len(entries) > 100:
            raise EvaluationContractError(f"surfaces.{surface} must be a list with at most 100 entries")
        normalized = []
        for index, item in enumerate(entries):
            entry = _object(item, f"surfaces.{surface}[{index}]")
            if set(entry) - {"fact_id", "value", "unit"}:
                raise EvaluationContractError(f"surfaces.{surface}[{index}] contains unsupported fields")
            normalized.append({"fact_id": _text(entry.get("fact_id"), f"surfaces.{surface}[{index}].fact_id", 64),
                               "value": entry.get("value"), "unit": _text(entry.get("unit", "unknown"), "surface unit", 80)})
        surfaces[surface] = normalized

    return {"schema_version": 1, "summary": _text(value.get("summary"), "summary"),
            "semantics": semantics,
            "questions": _text_list(value.get("questions", []), "questions", count=20),
            "facts": facts, "findings": findings, "claims": claims, "surfaces": surfaces,
            "limitations": _text_list(value.get("limitations", []), "limitations", count=30)}


def validate_evaluation_result(raw: Any) -> dict[str, Any]:
    """Validate the stable outer envelope before writing an evaluation artifact."""
    value = _object(raw, "evaluation result")
    if value.get("schema_version") != 1:
        raise EvaluationContractError("evaluation result schema_version must be 1")
    required = {"schema_version", "evaluation", "levels", "metrics", "performance", "failures", "observations"}
    if set(value) != required:
        raise EvaluationContractError("evaluation result has missing or unsupported top-level fields")
    evaluation = _object(value["evaluation"], "evaluation")
    if not {"run_id", "mode", "fixture", "candidate", "status"} <= evaluation.keys():
        raise EvaluationContractError("evaluation metadata is incomplete")
    levels = _object(value["levels"], "levels")
    if set(levels) != {"L1", "L2", "L3", "L4", "L5"}:
        raise EvaluationContractError("evaluation must report L1 through L5 separately")
    failures = value["failures"]
    if not isinstance(failures, list):
        raise EvaluationContractError("failures must be a list")
    for index, failure in enumerate(failures):
        entry = _object(failure, f"failures[{index}]")
        if entry.get("class") not in FAILURE_CLASSES:
            raise EvaluationContractError(f"failures[{index}] has an unknown taxonomy class")
        _text(entry.get("id"), f"failures[{index}].id", 128)
        _text(entry.get("summary"), f"failures[{index}].summary")
    if not isinstance(value["observations"], list) or not isinstance(value["metrics"], dict) or not isinstance(value["performance"], dict):
        raise EvaluationContractError("metrics, performance, or observations have an invalid shape")
    return value
