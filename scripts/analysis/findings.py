"""Evidence-linked findings, narrative contracts, and transparent materiality tiers."""

from __future__ import annotations

import json
import re
from typing import Any

from .contracts import EPISTEMIC_TYPES, CONFIDENCE, MATERIALITY_LEVELS, validate_analysis_plan, validate_semantic_model, validate_task_brief
from .errors import AnalysisError


_DIMENSIONS = ("magnitude", "breadth", "persistence", "decision_relevance", "confidence",
               "exception_severity", "novelty")
_LEVEL = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")


def validate_evidence(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise AnalysisError("CONTRACT_INVALID", "Each evidence item must be an object.")
    allowed = {"id", "claim", "epistemic", "confidence", "source", "method", "calculation", "data"}
    if set(item) - allowed:
        raise AnalysisError("CONTRACT_INVALID", "Evidence contains unsupported fields.")
    identifier = item.get("id")
    epistemic, confidence = item.get("epistemic", "OBSERVED"), item.get("confidence", "UNKNOWN")
    source = item.get("source")
    if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
        raise AnalysisError("CONTRACT_INVALID", "Evidence needs a valid stable ID.")
    if epistemic not in EPISTEMIC_TYPES or confidence not in CONFIDENCE:
        raise AnalysisError("CONTRACT_INVALID", f"Evidence {identifier} has an unsupported epistemic or confidence value.")
    if not isinstance(source, dict) or set(source) - {"type", "locator", "sha256"}:
        raise AnalysisError("EVIDENCE_PROVENANCE_INVALID", f"Evidence {identifier} needs source type, locator, and optional SHA-256.")
    if not isinstance(source.get("type"), str) or not source["type"].strip() or not isinstance(source.get("locator"), str) or not source["locator"].strip():
        raise AnalysisError("EVIDENCE_PROVENANCE_INVALID", f"Evidence {identifier} has incomplete source provenance.")
    digest = source.get("sha256")
    if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)):
        raise AnalysisError("EVIDENCE_PROVENANCE_INVALID", f"Evidence {identifier} has an invalid SHA-256.")
    claim = item.get("claim")
    if not isinstance(claim, str) or not claim.strip() or len(claim) > 3000:
        raise AnalysisError("CONTRACT_INVALID", f"Evidence {identifier} needs a concise claim.")
    result: dict[str, Any] = {"id": identifier, "claim": claim.strip(), "epistemic": epistemic,
                              "confidence": confidence,
                              "source": {"type": source["type"].strip(), "locator": source["locator"].strip(), "sha256": digest}}
    for field in ("method", "calculation"):
        value = item.get(field)
        if value is not None:
            if not isinstance(value, str) or not value.strip() or len(value) > 2000:
                raise AnalysisError("CONTRACT_INVALID", f"Evidence {identifier} {field} must be short text.")
            result[field] = value.strip()
    if "data" in item:
        try:
            encoded = json.dumps(item["data"], ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            raise AnalysisError("CONTRACT_INVALID", f"Evidence {identifier} data must be JSON-compatible.") from None
        if len(encoded.encode("utf-8")) > 100_000:
            raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", f"Evidence {identifier} exceeds the 100 KiB result limit.")
        result["data"] = item["data"]
    return result


def validate_finding(item: Any) -> dict[str, Any]:
    allowed = {"id", "question", "statement", "type", "evidence_ids", "confidence", "materiality",
               "periods", "segment", "magnitude", "unit", "caveats", "alternatives", "operation_id"}
    if not isinstance(item, dict) or set(item) - allowed:
        raise AnalysisError("CONTRACT_INVALID", "Finding has an invalid shape.")
    identifier = item.get("id")
    finding_type, confidence = item.get("type"), item.get("confidence", "UNKNOWN")
    if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
        raise AnalysisError("CONTRACT_INVALID", "Finding needs a valid stable ID.")
    if finding_type not in EPISTEMIC_TYPES or confidence not in CONFIDENCE:
        raise AnalysisError("CONTRACT_INVALID", f"Finding {identifier} has an unsupported type or confidence.")
    refs = item.get("evidence_ids", [])
    if not isinstance(refs, list) or len(refs) > 100 or any(not isinstance(ref, str) or not _ID.fullmatch(ref) for ref in refs) or len(refs) != len(set(refs)):
        raise AnalysisError("CONTRACT_INVALID", f"Finding {identifier} evidence IDs are invalid.")
    if finding_type != "UNKNOWN" and not refs:
        raise AnalysisError("EVIDENCE_INSUFFICIENT", f"Finding {identifier} requires evidence or must be labeled UNKNOWN.")
    materiality = item.get("materiality")
    if not isinstance(materiality, dict) or set(materiality) - {"overall", "dimensions", "rationale"}:
        raise AnalysisError("CONTRACT_INVALID", f"Finding {identifier} materiality must include explainable dimensions.")
    overall = materiality.get("overall", "UNKNOWN")
    dimensions = materiality.get("dimensions", {})
    if overall not in MATERIALITY_LEVELS or not isinstance(dimensions, dict) or set(dimensions) - set(_DIMENSIONS):
        raise AnalysisError("CONTRACT_INVALID", f"Finding {identifier} materiality levels are invalid.")
    normalized_dimensions = {}
    for dimension in _DIMENSIONS:
        level = dimensions.get(dimension, "UNKNOWN")
        if level not in MATERIALITY_LEVELS:
            raise AnalysisError("CONTRACT_INVALID", f"Finding {identifier} materiality {dimension} is invalid.")
        normalized_dimensions[dimension] = level
    rationale = materiality.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 1500:
        raise AnalysisError("CONTRACT_INVALID", f"Finding {identifier} needs a materiality rationale.")
    def strings(field: str, maximum: int, item_maximum: int = 1000) -> list[str]:
        values = item.get(field, [])
        if not isinstance(values, list) or len(values) > maximum or any(not isinstance(value, str) or not value.strip() or len(value) > item_maximum for value in values):
            raise AnalysisError("CONTRACT_INVALID", f"Finding {identifier} {field} is not a bounded text list.")
        return [value.strip() for value in values]
    periods = strings("periods", 20, 240)
    result = {"id": identifier, "question": _text(item.get("question"), f"finding {identifier} question", 1000),
              "statement": _text(item.get("statement"), f"finding {identifier} statement", 3000),
              "type": finding_type, "evidence_ids": refs, "confidence": confidence,
              "materiality": {"overall": overall, "dimensions": normalized_dimensions, "rationale": rationale.strip()},
              "periods": periods, "segment": _text(item.get("segment", ""), f"finding {identifier} segment", 500, required=False),
              "magnitude": _text(item.get("magnitude", ""), f"finding {identifier} magnitude", 300, required=False),
              "unit": _text(item.get("unit", ""), f"finding {identifier} unit", 120, required=False),
              "caveats": strings("caveats", 20), "alternatives": strings("alternatives", 20)}
    operation_id = item.get("operation_id")
    if operation_id is not None:
        if not isinstance(operation_id, str) or not _ID.fullmatch(operation_id):
            raise AnalysisError("CONTRACT_INVALID", f"Finding {identifier} operation_id is invalid.")
        result["operation_id"] = operation_id
    return result


def rank_materiality(findings: list[dict[str, Any]]) -> list[list[str]]:
    """Pareto tiers across named dimensions; no opaque weighted total is calculated."""
    checked = [validate_finding(item) for item in findings]
    if len({item["id"] for item in checked}) != len(checked):
        raise AnalysisError("CONTRACT_INVALID", "Finding IDs must be unique before materiality ranking.")
    remaining = list(checked)
    tiers: list[list[str]] = []
    while remaining:
        front = []
        for candidate in remaining:
            dimensions = candidate["materiality"]["dimensions"]
            dominated = False
            for other in remaining:
                if other is candidate:
                    continue
                other_values = other["materiality"]["dimensions"]
                comparisons = [_LEVEL[other_values[key]] - _LEVEL[dimensions[key]] for key in _DIMENSIONS]
                if all(value >= 0 for value in comparisons) and any(value > 0 for value in comparisons):
                    dominated = True
                    break
            if not dominated:
                front.append(candidate)
        front.sort(key=lambda item: item["id"])
        tiers.append([item["id"] for item in front])
        front_ids = {item["id"] for item in front}
        remaining = [item for item in remaining if item["id"] not in front_ids]
    return tiers


def validate_narrative(raw: Any, finding_ids: set[str]) -> dict[str, Any]:
    fields = {"main_conclusion", "context", "what_changed", "explanation", "unresolved", "risks_opportunities",
              "next_actions", "finding_ids"}
    if not isinstance(raw, dict) or set(raw) - fields:
        raise AnalysisError("CONTRACT_INVALID", "Narrative has an invalid shape.")
    refs = raw.get("finding_ids", [])
    if not isinstance(refs, list) or len(refs) > 100 or len(refs) != len(set(refs)) or set(refs) - finding_ids:
        raise AnalysisError("EVIDENCE_PROVENANCE_INVALID", "Narrative references an unknown or repeated finding.")
    def list_field(name: str) -> list[str]:
        values = raw.get(name, [])
        if not isinstance(values, list) or len(values) > 20 or any(not isinstance(value, str) or not value.strip() or len(value) > 1500 for value in values):
            raise AnalysisError("CONTRACT_INVALID", f"Narrative {name} must be a bounded text list.")
        return [value.strip() for value in values]
    return {"main_conclusion": _text(raw.get("main_conclusion"), "narrative.main_conclusion", 3000),
            "context": _text(raw.get("context", ""), "narrative.context", 2000, required=False),
            "what_changed": list_field("what_changed"), "explanation": list_field("explanation"),
            "unresolved": list_field("unresolved"), "risks_opportunities": list_field("risks_opportunities"),
            "next_actions": list_field("next_actions"), "finding_ids": refs}


def validate_result(raw: Any) -> dict[str, Any]:
    fields = {"schema_version", "task_brief", "profile", "semantic_model", "questions", "plan",
              "evidence", "findings", "narrative", "limitations"}
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or set(raw) - fields:
        raise AnalysisError("CONTRACT_INVALID", "Analytical result must be schema_version 1 with supported fields.")
    brief = validate_task_brief(raw.get("task_brief"))
    profile = validate_profile(raw.get("profile"))
    known_columns = {item["name"] for item in profile["columns"]}
    semantics = validate_semantic_model(raw.get("semantic_model"), known_columns=known_columns)
    questions = raw.get("questions", [])
    if not isinstance(questions, list) or len(questions) > 12 or any(not isinstance(value, str) or not value.strip() for value in questions):
        raise AnalysisError("CONTRACT_INVALID", "Analytical questions must be a bounded list of text.")
    plan = validate_analysis_plan(raw.get("plan"))
    if plan["source_sha256"] != profile["source"]["sha256"]:
        raise AnalysisError("INPUT_SOURCE_CHANGED", "Analytical plan and profile refer to different source snapshots.")
    semantic_columns = {item["name"]: item for item in semantics["columns"]}
    for operation in plan["operations"]:
        column = operation.get("column")
        if column in semantic_columns:
            known_unit = semantic_columns[column]["unit"]
            requested_unit = operation.get("unit")
            if known_unit.casefold() != "unknown" and requested_unit not in {None, known_unit}:
                raise AnalysisError("UNIT_MISMATCH", f"Operation {operation['id']} unit conflicts with semantic field {column!r}.")
            if known_unit.casefold() != "unknown" and requested_unit is None:
                operation["unit"] = known_unit
        if operation["operation"] == "ratio":
            for field, unit_field in (("numerator", "numerator_unit"), ("denominator", "denominator_unit")):
                known_unit = semantic_columns.get(operation[field], {}).get("unit", "unknown")
                if known_unit.casefold() != "unknown" and operation[unit_field] != known_unit:
                    raise AnalysisError("UNIT_MISMATCH", f"Operation {operation['id']} {unit_field} conflicts with semantic field {operation[field]!r}.")
    evidence_raw, findings_raw = raw.get("evidence", []), raw.get("findings", [])
    if not isinstance(evidence_raw, list) or len(evidence_raw) > 200 or not isinstance(findings_raw, list) or len(findings_raw) > 100:
        raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", "Analytical result exceeds the evidence or finding limits.")
    evidence = [validate_evidence(item) for item in evidence_raw]
    findings = [validate_finding(item) for item in findings_raw]
    evidence_ids = {item["id"] for item in evidence}
    finding_ids = {item["id"] for item in findings}
    if len(evidence_ids) != len(evidence) or len(finding_ids) != len(findings):
        raise AnalysisError("CONTRACT_INVALID", "Evidence and finding IDs must be unique.")
    for finding in findings:
        missing = set(finding["evidence_ids"]) - evidence_ids
        if missing:
            raise AnalysisError("EVIDENCE_PROVENANCE_INVALID", f"Finding {finding['id']} references unknown evidence IDs: {', '.join(sorted(missing))}.")
    narrative = validate_narrative(raw.get("narrative"), finding_ids)
    limitations = raw.get("limitations", [])
    if not isinstance(limitations, list) or len(limitations) > 30 or any(not isinstance(value, str) or not value.strip() for value in limitations):
        raise AnalysisError("CONTRACT_INVALID", "Result limitations must be a bounded text list.")
    return {"schema_version": 1, "task_brief": brief, "profile": profile, "semantic_model": semantics,
            "questions": questions, "plan": plan, "evidence": evidence, "findings": findings,
            "materiality_tiers": rank_materiality(findings), "narrative": narrative,
            "limitations": limitations}


def validate_profile(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise AnalysisError("CONTRACT_INVALID", "Data profile must use schema_version 1.")
    source = raw.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("type"), str) or not isinstance(source.get("locator"), str) or not isinstance(source.get("sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", source["sha256"]):
        raise AnalysisError("EVIDENCE_PROVENANCE_INVALID", "Data profile needs a named source and SHA-256 snapshot identity.")
    columns = raw.get("columns")
    if not isinstance(columns, list) or not 1 <= len(columns) <= 200:
        raise AnalysisError("CONTRACT_INVALID", "Data profile must contain 1 to 200 columns.")
    names = []
    for index, item in enumerate(columns):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise AnalysisError("CONTRACT_INVALID", f"Data profile column {index} has no name.")
        names.append(item["name"])
    if len(set(names)) != len(names):
        raise AnalysisError("CONTRACT_INVALID", "Data profile column names must be unique.")
    row_count, profiled_rows = raw.get("row_count"), raw.get("profiled_rows")
    if (isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0
            or isinstance(profiled_rows, bool) or not isinstance(profiled_rows, int)
            or not 0 <= profiled_rows <= row_count):
        raise AnalysisError("CONTRACT_INVALID", "Data profile row counts are invalid.")
    if raw.get("column_count") != len(columns) or raw.get("statistics_scope") not in {"complete", "sampled_prefix"}:
        raise AnalysisError("CONTRACT_INVALID", "Data profile column count or statistics scope is inconsistent.")
    if (raw["statistics_scope"] == "complete") != (profiled_rows == row_count):
        raise AnalysisError("CONTRACT_INVALID", "Data profile completeness label does not match profiled row counts.")
    return raw


def _text(value: Any, field: str, maximum: int, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > maximum:
        raise AnalysisError("CONTRACT_INVALID", f"{field} must be text of at most {maximum} characters.")
    return value.strip()
