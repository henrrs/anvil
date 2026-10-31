"""Evidence-linked hypothesis and candidate-claim checks for task-local analysis."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import AnalysisError


_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")
_CLASSIFICATIONS = {"OBSERVED", "DERIVED", "SUPPORTED", "INFERRED", "HYPOTHESIS", "UNKNOWN"}
_CLAIM_TYPES = {"general", "observation_count", "entity_count", "trend", "broad_based_change", "like_for_like", "coverage", "period_comparison", "composition", "causal"}
_CLAIM_STATUS = {"VALIDATED", "QUALIFIED", "REJECTED", "UNKNOWN"}


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def validate_hypotheses(raw: Any, evidence_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > 50:
        raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", "Hypotheses must be a list of at most 50 items.")
    result = []
    seen = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) - {"id", "question", "explanation", "status", "evidence_ids", "confidence", "limitations"}:
            raise AnalysisError("CONTRACT_INVALID", f"hypotheses[{index}] has an invalid shape.")
        identifier = item.get("id")
        status = item.get("status")
        confidence = item.get("confidence", "UNKNOWN")
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier) or identifier in seen:
            raise AnalysisError("CONTRACT_INVALID", "Hypothesis IDs must be unique valid identifiers.")
        if status not in {"SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_SUPPORTED", "UNKNOWN"}:
            raise AnalysisError("CONTRACT_INVALID", f"Hypothesis {identifier} has an invalid evidence status.")
        if confidence not in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
            raise AnalysisError("CONTRACT_INVALID", f"Hypothesis {identifier} has an invalid confidence.")
        refs = item.get("evidence_ids", [])
        if (not isinstance(refs, list) or len(refs) > 50
                or any(not isinstance(ref, str) or not _ID.fullmatch(ref) for ref in refs)
                or len(refs) != len(set(refs))):
            raise AnalysisError("CONTRACT_INVALID", f"Hypothesis {identifier} evidence IDs are invalid.")
        missing = set(refs) - evidence_ids
        if missing:
            raise AnalysisError("EVIDENCE_PROVENANCE_INVALID", f"Hypothesis {identifier} references unknown evidence IDs: {', '.join(sorted(missing))}.")
        if status != "UNKNOWN" and not refs:
            raise AnalysisError("EVIDENCE_INSUFFICIENT", f"Hypothesis {identifier} requires evidence or must remain UNKNOWN.")
        limitations = item.get("limitations", [])
        if not isinstance(limitations, list) or len(limitations) > 20 or any(not isinstance(value, str) or not value.strip() or len(value) > 1000 for value in limitations):
            raise AnalysisError("CONTRACT_INVALID", f"Hypothesis {identifier} limitations must be a bounded text list.")
        result.append({"id": identifier, "question": _text(item.get("question"), f"hypothesis {identifier} question", 1000),
                       "explanation": _text(item.get("explanation"), f"hypothesis {identifier} explanation", 2000),
                       "status": status, "confidence": confidence, "evidence_ids": refs,
                       "limitations": [value.strip() for value in limitations]})
        seen.add(identifier)
    return result


def _aligned_coverage_pairs(metric_operation: dict[str, Any], metric_record: dict[str, Any],
                            plan_operations: dict[str, dict[str, Any]],
                            execution_operations: dict[str, dict[str, Any]]) -> list[tuple[Any, Any]]:
    period_field = metric_operation.get("period_column")
    if not period_field:
        return []
    metric_group = metric_record.get("group", {})
    if not isinstance(metric_group, dict):
        return []
    pairs = []
    for identifier, candidate in plan_operations.items():
        if candidate["operation"] != "coverage":
            continue
        dimensions = candidate.get("group_by", [])
        if period_field not in dimensions or not set(metric_operation.get("group_by", [])) <= (set(dimensions) - {period_field}):
            continue
        entry = execution_operations.get(identifier)
        coverage_records = entry.get("results", []) if isinstance(entry, dict) else []
        by_period: dict[str, list[Any]] = {"baseline": [], "current": []}
        for coverage_record in coverage_records:
            if not isinstance(coverage_record, dict):
                continue
            group = coverage_record.get("group", {})
            if not isinstance(group, dict) or any(group.get(name) != metric_group.get(name)
                                                  for name in metric_operation.get("group_by", [])):
                continue
            if group.get(period_field) == metric_operation.get("baseline"):
                by_period["baseline"].append(coverage_record.get("coverage_ratio"))
            elif group.get(period_field) == metric_operation.get("current"):
                by_period["current"].append(coverage_record.get("coverage_ratio"))
        if len(by_period["baseline"]) == len(by_period["current"]) == 1:
            pairs.append((by_period["baseline"][0], by_period["current"][0]))
    return pairs


def validate_claims(raw: Any, *, evidence_ids: set[str], plan: dict[str, Any], execution: Any = None,
                    semantic_context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > 100:
        raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", "Claims must be a list of at most 100 items.")
    plan_operations = {item["id"]: item for item in plan["operations"]}
    execution_operations = {}
    if isinstance(execution, dict) and isinstance(execution.get("operations"), list):
        execution_operations = {item.get("id"): item for item in execution["operations"] if isinstance(item, dict)}
    result = []
    seen = set()
    for index, item in enumerate(raw):
        allowed = {"id", "statement", "classification", "claim_type", "confidence", "evidence_ids", "operation_id",
                   "population", "periods", "direction", "threshold", "calculation", "limitations", "qualifier"}
        if not isinstance(item, dict) or set(item) - allowed:
            raise AnalysisError("CONTRACT_INVALID", f"claims[{index}] has an invalid shape.")
        identifier = item.get("id")
        classification, claim_type = item.get("classification"), item.get("claim_type", "general")
        confidence = item.get("confidence", "UNKNOWN")
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier) or identifier in seen:
            raise AnalysisError("CONTRACT_INVALID", "Claim IDs must be unique valid identifiers.")
        if classification not in _CLASSIFICATIONS or claim_type not in _CLAIM_TYPES:
            raise AnalysisError("CONTRACT_INVALID", f"Claim {identifier} has an unsupported classification or type.")
        if confidence not in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
            raise AnalysisError("CONTRACT_INVALID", f"Claim {identifier} has an invalid confidence.")
        refs = item.get("evidence_ids", [])
        if (not isinstance(refs, list) or len(refs) > 100
                or any(not isinstance(ref, str) or not _ID.fullmatch(ref) for ref in refs)
                or len(refs) != len(set(refs))):
            raise AnalysisError("CONTRACT_INVALID", f"Claim {identifier} evidence IDs are invalid.")
        missing = set(refs) - evidence_ids
        if missing:
            raise AnalysisError("EVIDENCE_PROVENANCE_INVALID", f"Claim {identifier} references unknown evidence IDs: {', '.join(sorted(missing))}.")
        if classification != "UNKNOWN" and not refs:
            raise AnalysisError("EVIDENCE_INSUFFICIENT", f"Claim {identifier} requires evidence or must be classified UNKNOWN.")

        operation_id = item.get("operation_id")
        if operation_id is not None and (not isinstance(operation_id, str) or not _ID.fullmatch(operation_id)):
            raise AnalysisError("CONTRACT_INVALID", f"Claim {identifier} operation_id is invalid.")
        if operation_id is not None and operation_id not in plan_operations:
            raise AnalysisError("EVIDENCE_PROVENANCE_INVALID", f"Claim {identifier} references an operation outside the validated plan.")
        periods = item.get("periods", [])
        limitations = item.get("limitations", [])
        for field, values, maximum in (("periods", periods, 20), ("limitations", limitations, 20)):
            if (not isinstance(values, list) or len(values) > maximum
                    or any(not isinstance(value, str) or not value.strip() or len(value) > 1000 for value in values)):
                raise AnalysisError("CONTRACT_INVALID", f"Claim {identifier} {field} must be a bounded text list.")
        population = item.get("population")
        if population is not None and not isinstance(population, dict):
            raise AnalysisError("CONTRACT_INVALID", f"Claim {identifier} population must be an object or null.")
        qualifier = item.get("qualifier", "")
        calculation = item.get("calculation", "")
        if not isinstance(qualifier, str) or len(qualifier) > 1500 or not isinstance(calculation, str) or len(calculation) > 1500:
            raise AnalysisError("CONTRACT_INVALID", f"Claim {identifier} qualifier or calculation is invalid.")

        status, reason = "QUALIFIED", "Evidence references are valid; semantic wording was not independently established."
        operation = plan_operations.get(operation_id)
        observed = execution_operations.get(operation_id)
        observed_records = observed.get("results", []) if isinstance(observed, dict) else []
        if classification == "UNKNOWN":
            status, reason = "UNKNOWN", "The claim is explicitly marked UNKNOWN."
        elif classification == "HYPOTHESIS" or claim_type == "causal":
            status, reason = "QUALIFIED", "Causality is not established by this deterministic evidence path; retain this as a hypothesis."
            if claim_type == "causal" and classification != "HYPOTHESIS":
                status, reason = "REJECTED", "Causal wording requires a HYPOTHESIS classification; the available operations establish no causal design."
        elif claim_type in {"observation_count", "entity_count"}:
            expected_basis = "rows" if claim_type == "observation_count" else None
            key_fields = population.get("key_fields") if isinstance(population, dict) else None
            if claim_type == "entity_count":
                if not isinstance(key_fields, list) or not key_fields or any(not isinstance(field, str) for field in key_fields):
                    status, reason = "REJECTED", "Entity cardinality requires one or more explicit key fields."
                else:
                    expected_basis = "distinct_key" if len(key_fields) == 1 else "distinct_composite_key"
            if (not isinstance(population, dict) or expected_basis is None
                    or population.get("basis") != expected_basis):
                status, reason = "REJECTED", "Population cardinality basis does not match the claimed observation/entity count."
            elif not isinstance(population.get("count"), int) or isinstance(population.get("count"), bool) or population["count"] < 0:
                raise AnalysisError("CONTRACT_INVALID", f"Claim {identifier} population count must be a non-negative integer.")
            elif observed is None:
                status, reason = "UNKNOWN", "No deterministic operation result is available to validate the population count."
            elif claim_type == "observation_count":
                if operation is None or operation["operation"] != "count" or len(observed_records) != 1:
                    status, reason = "REJECTED", "Observation counts must reference one ungrouped count operation."
                else:
                    actual = observed_records[0].get("value")
                    status, reason = (("VALIDATED", "Count matches the deterministic observation count.") if str(population["count"]) == str(actual)
                                      else ("REJECTED", "Claimed row count differs from the deterministic observation count."))
            else:
                planned_fields = (operation.get("columns") or [operation.get("column")]) if operation else []
                if operation is None or operation["operation"] != "distinct_count" or key_fields != planned_fields or len(observed_records) != 1:
                    status, reason = "REJECTED", "Entity counts must reference a distinct_count operation over the claimed key fields."
                else:
                    actual = observed_records[0].get("value")
                    status, reason = (("VALIDATED", "Distinct count matches the deterministic candidate-key count.") if str(population["count"]) == str(actual)
                                      else ("REJECTED", "Claimed entity count differs from the deterministic distinct-key count."))
                    if status == "VALIDATED":
                        matching_entity = next((candidate for candidate in (semantic_context or {}).get("entities", [])
                                                if sorted(candidate.get("fields", [])) == sorted(key_fields)), None)
                        if matching_entity is None or (semantic_context or {}).get("focus") == "numeric":
                            status, reason = "QUALIFIED", "The distinct key count is verified, but available semantic evidence does not establish that the key identifies the claimed persistent entity."
                            confidence = "LOW" if semantic_context is not None else "UNKNOWN"
                            limitations = list(limitations) + ["Distinct values are a candidate-key count; entity semantics remain unverified."]
                        elif matching_entity.get("confidence") in {"LOW", "UNKNOWN"}:
                            status, reason = "QUALIFIED", "The distinct key count is verified, but the entity-key candidate has insufficient semantic confidence for a definitive entity claim."
                            confidence = "LOW" if matching_entity.get("confidence") == "LOW" else "UNKNOWN"
                            limitations = list(limitations) + ["Entity-key semantics have low or unknown confidence."]
                        elif matching_entity.get("confidence") == "MEDIUM" and confidence == "HIGH":
                            confidence = "MEDIUM"
        elif claim_type == "trend":
            if operation is None or operation["operation"] != "trend" or not observed_records:
                status, reason = "REJECTED", "Trend claims require a deterministic trend operation."
            elif any(record.get("trend_supported") is not True or record.get("point_count", 0) < 3 for record in observed_records):
                status, reason = "REJECTED", "Available temporal evidence supports a comparison, not a persistent trend."
            else:
                status, reason = "VALIDATED", "Trend claim has at least three observed points in each referenced series."
        elif claim_type == "like_for_like":
            if operation is None or operation["operation"] != "cohort" or not observed_records:
                status, reason = "REJECTED", "Like-for-like claims require a deterministic cohort operation."
            elif observed_records[0].get("like_for_like_delta") is None:
                status, reason = "UNKNOWN", "The retained cohort has no comparable measured values."
            else:
                status, reason = "VALIDATED", "A common-key cohort comparison is present in the operation evidence."
        elif claim_type == "broad_based_change":
            threshold = item.get("threshold")
            direction = item.get("direction")
            if operation is None or operation["operation"] != "cohort" or not observed_records:
                status, reason = "REJECTED", "Breadth claims require entity-level cohort evidence."
            elif direction not in {"increase", "decrease"} or operation.get("improvement_direction") != direction:
                status, reason = "UNKNOWN", "No matching direction was declared for entity-level changes."
            elif isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
                status, reason = "UNKNOWN", "Breadth needs an explicit threshold between zero and one."
            else:
                share = observed_records[0].get("improved_share")
                if share is None:
                    status, reason = "UNKNOWN", "The cohort has no comparable entity-level measurements."
                elif isinstance(share, bool) or not isinstance(share, (str, int, float)):
                    status, reason = "UNKNOWN", "The deterministic cohort share is not numeric."
                elif Decimal(str(share)) >= Decimal(str(threshold)):
                    status, reason = "VALIDATED", "Observed improved share meets the explicit breadth threshold."
                else:
                    status, reason = "REJECTED", "Observed improved share is below the explicit breadth threshold."
        elif claim_type == "coverage":
            if operation is None or operation["operation"] != "coverage" or not observed_records:
                status, reason = "UNKNOWN", "Coverage claims require an explicit deterministic coverage operation."
            elif any(record.get("coverage_ratio") is None for record in observed_records):
                status, reason = "UNKNOWN", "Coverage denominator is missing, zero, or unavailable."
            else:
                status, reason = "VALIDATED", "Coverage ratios were calculated from an explicit eligible denominator."
        elif claim_type == "period_comparison":
            if operation is None or operation["operation"] not in {"delta", "delta_percent", "delta_percentage_points"} or not observed_records:
                status, reason = "REJECTED", "Period comparisons require deterministic delta evidence."
            else:
                coverage_pairs = [pair for record in observed_records
                                  for pair in _aligned_coverage_pairs(operation, record, plan_operations, execution_operations)]
                if not coverage_pairs:
                    status, reason, confidence = "UNKNOWN", "Coverage comparability was not established for the compared periods.", "UNKNOWN"
                elif any(before is None or after is None for before, after in coverage_pairs):
                    status, reason, confidence = "UNKNOWN", "Coverage evidence is incomplete for the compared population.", "UNKNOWN"
                elif any(str(before) != str(after) for before, after in coverage_pairs):
                    status, reason, confidence = "QUALIFIED", "Coverage changed across the available comparison; confidence is reduced.", "LOW"
                    limitations = list(limitations) + ["Coverage changed across the compared periods."]
                elif len(coverage_pairs) != len(observed_records):
                    status, reason, confidence = "UNKNOWN", "Coverage was not measured for every compared group.", "UNKNOWN"
                else:
                    status, reason = "VALIDATED", "Coverage is stable across the compared periods and matching groups."
        elif claim_type == "composition":
            if operation is None or operation["operation"] != "composition" or not observed_records:
                status, reason = "REJECTED", "Composition claims require a deterministic category-composition operation."
            else:
                shift = _decimal(observed_records[0].get("composition_shift"))
                threshold = item.get("threshold", 0)
                if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
                    status, reason = "UNKNOWN", "Composition claims need a valid measured-share threshold between zero and one."
                elif shift is None:
                    status, reason = "UNKNOWN", "Population shares could not be compared for both periods."
                elif shift > Decimal(str(threshold)):
                    status, reason = "VALIDATED", "Observed category-share movement meets the declared threshold."
                else:
                    status, reason = "REJECTED", "Observed category-share movement does not exceed the declared threshold."

        if status == "REJECTED" and confidence in {"HIGH", "MEDIUM"}:
            confidence = "LOW"
        elif status == "UNKNOWN":
            confidence = "UNKNOWN"
        result.append({"id": identifier, "statement": _text(item.get("statement"), f"claim {identifier} statement", 3000),
                       "classification": classification, "claim_type": claim_type, "confidence": confidence,
                       "evidence_ids": refs, "operation_id": operation_id, "population": population,
                       "periods": [value.strip() for value in periods], "calculation": calculation.strip(),
                       "limitations": [value.strip() for value in limitations], "qualifier": qualifier.strip(),
                       "validation": {"status": status, "reason": reason}})
        seen.add(identifier)
    return result


def _text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise AnalysisError("CONTRACT_INVALID", f"{field} must be non-empty text of at most {maximum} characters.")
    return value.strip()
