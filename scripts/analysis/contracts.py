"""Versioned model-facing contracts for intent and bounded analytical plans."""

from __future__ import annotations

import re
from typing import Any

from .errors import AnalysisError


IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")
DEPTHS = {"FAST", "STANDARD", "DEEP"}
CONFIDENCE = {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}
ROLES = {"identifier", "entity", "entity_key", "event", "event_key", "candidate_key",
         "observation_grain", "relationship", "temporal_dimension", "dimension", "measure",
         "rate", "status", "unknown"}
EPISTEMIC_TYPES = {"OBSERVED", "DERIVED", "SUPPORTED", "INTERPRETED", "INFERRED", "HYPOTHESIS", "UNKNOWN"}
MATERIALITY_LEVELS = {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}
OPERATIONS = {
    "count", "distinct_count", "sum", "mean", "median", "percentile", "min", "max",
    "ratio", "share", "delta", "delta_percent", "delta_percentage_points", "rank",
    "top_n", "bottom_n", "distribution", "trend", "volatility", "coverage", "cohort",
    "concentration", "correlation", "contribution", "composition",
}
_AGGREGATES = {"count", "sum", "mean", "median", "min", "max"}
_PLAN_FIELDS = {
    "id", "operation", "column", "columns", "group_by", "percentile", "limit", "period_column",
    "baseline", "current", "aggregate", "entity_column", "entity_columns", "improvement_direction", "numerator", "denominator",
    "x_column", "y_column", "unit", "numerator_unit", "denominator_unit", "result_unit",
}


def _text(value: Any, field: str, *, maximum: int = 4000, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > maximum:
        raise AnalysisError("CONTRACT_INVALID", f"{field} must be non-empty text of at most {maximum} characters.")
    return value.strip()


def _text_list(value: Any, field: str, *, maximum: int = 30, item_maximum: int = 1000) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise AnalysisError("CONTRACT_INVALID", f"{field} must be a list with at most {maximum} entries.")
    result = [_text(item, f"{field}[{index}]", maximum=item_maximum) for index, item in enumerate(value)]
    return result  # type: ignore[return-value]


def validate_task_brief(raw: Any, *, original_request: str | None = None) -> dict[str, Any]:
    """Validate model-compiled intent while retaining the exact user request."""
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise AnalysisError("CONTRACT_INVALID", "Task brief must be an object with schema_version 1.")
    allowed = {
        "schema_version", "original_request", "objective", "audience", "expected_outcome",
        "explicit_requirements", "derived_requirements", "constraints", "quality_attributes",
        "evidence_expectations", "ambiguities", "non_goals", "success_criteria",
    }
    if set(raw) - allowed:
        raise AnalysisError("CONTRACT_INVALID", "Task brief contains unsupported fields.")
    request = raw.get("original_request")
    if not isinstance(request, str) or not request.strip() or len(request) > 12000:
        raise AnalysisError("CONTRACT_INVALID", "original_request must preserve non-empty text of at most 12000 characters.")
    if original_request is not None and request != original_request:
        raise AnalysisError("INTENT_PROVENANCE_INVALID", "Task brief must preserve the original user request exactly.")

    def requirements(field: str, *, derived: bool) -> list[dict[str, str]]:
        values = raw.get(field, [])
        if not isinstance(values, list) or len(values) > 40:
            raise AnalysisError("CONTRACT_INVALID", f"{field} must contain at most 40 requirements.")
        result = []
        for index, item in enumerate(values):
            if not isinstance(item, dict) or set(item) - {"text", "rationale"}:
                raise AnalysisError("CONTRACT_INVALID", f"{field}[{index}] has an invalid shape.")
            entry = {"text": _text(item.get("text"), f"{field}[{index}].text", maximum=1000)}
            rationale = _text(item.get("rationale"), f"{field}[{index}].rationale", maximum=1000,
                              required=derived)
            if rationale is not None:
                entry["rationale"] = rationale
            result.append(entry)
        return result

    ambiguities_raw = raw.get("ambiguities", [])
    if not isinstance(ambiguities_raw, list) or len(ambiguities_raw) > 20:
        raise AnalysisError("CONTRACT_INVALID", "ambiguities must contain at most 20 entries.")
    ambiguities = []
    for index, item in enumerate(ambiguities_raw):
        if not isinstance(item, dict) or set(item) - {"question", "material", "impact"}:
            raise AnalysisError("CONTRACT_INVALID", f"ambiguities[{index}] has an invalid shape.")
        if not isinstance(item.get("material"), bool):
            raise AnalysisError("CONTRACT_INVALID", f"ambiguities[{index}].material must be boolean.")
        ambiguities.append({"question": _text(item.get("question"), f"ambiguities[{index}].question", maximum=1000),
                            "material": item["material"],
                            "impact": _text(item.get("impact", ""), f"ambiguities[{index}].impact", maximum=1000, required=False)})
    return {
        "schema_version": 1, "original_request": request,
        "objective": _text(raw.get("objective"), "objective", maximum=2000),
        "audience": _text(raw.get("audience", "unknown"), "audience", maximum=160),
        "expected_outcome": _text(raw.get("expected_outcome", ""), "expected_outcome", maximum=1000, required=False),
        "explicit_requirements": requirements("explicit_requirements", derived=False),
        "derived_requirements": requirements("derived_requirements", derived=True),
        "constraints": _text_list(raw.get("constraints", []), "constraints", maximum=40),
        "quality_attributes": _text_list(raw.get("quality_attributes", []), "quality_attributes", maximum=20),
        "evidence_expectations": _text_list(raw.get("evidence_expectations", []), "evidence_expectations", maximum=20),
        "ambiguities": ambiguities,
        "non_goals": _text_list(raw.get("non_goals", []), "non_goals", maximum=30),
        "success_criteria": _text_list(raw.get("success_criteria", []), "success_criteria", maximum=30),
    }


def validate_semantic_model(raw: Any, *, known_columns: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise AnalysisError("CONTRACT_INVALID", "Semantic model must be an object with schema_version 1.")
    if set(raw) - {"schema_version", "columns", "open_questions"}:
        raise AnalysisError("CONTRACT_INVALID", "Semantic model contains unsupported fields.")
    columns_raw = raw.get("columns", [])
    if not isinstance(columns_raw, list) or len(columns_raw) > 200:
        raise AnalysisError("CONTRACT_INVALID", "Semantic model columns must be bounded to 200 entries.")
    columns = []
    seen = set()
    for index, item in enumerate(columns_raw):
        if not isinstance(item, dict) or set(item) - {"name", "role", "confidence", "interpretation", "rationale", "unit"}:
            raise AnalysisError("CONTRACT_INVALID", f"semantic columns[{index}] has an invalid shape.")
        name = _text(item.get("name"), f"semantic columns[{index}].name", maximum=240)
        role, confidence = item.get("role"), item.get("confidence")
        if name in seen or (known_columns is not None and name not in known_columns):
            raise AnalysisError("SEMANTIC_REFERENCE_INVALID", f"Semantic field {name!r} is duplicated or absent from the profile.")
        if role not in ROLES or confidence not in CONFIDENCE:
            raise AnalysisError("CONTRACT_INVALID", f"semantic columns[{index}] has an unsupported role or confidence.")
        seen.add(name)
        unit = _text(item.get("unit", "unknown"), f"semantic columns[{index}].unit", maximum=80)
        columns.append({"name": name, "role": role, "confidence": confidence,
                        "interpretation": _text(item.get("interpretation"), f"semantic columns[{index}].interpretation", maximum=500),
                        "rationale": _text(item.get("rationale", ""), f"semantic columns[{index}].rationale", maximum=500, required=False),
                        "unit": unit})
    return {"schema_version": 1, "columns": columns,
            "open_questions": _text_list(raw.get("open_questions", []), "semantic open_questions", maximum=12)}


def validate_analysis_plan(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise AnalysisError("CONTRACT_INVALID", "Analysis plan must be an object with schema_version 1.")
    if set(raw) - {"schema_version", "source_sha256", "depth", "primary_question", "questions", "operations", "stop_conditions", "budgets"}:
        raise AnalysisError("CONTRACT_INVALID", "Analysis plan contains unsupported fields.")
    source_sha256 = raw.get("source_sha256")
    if not isinstance(source_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", source_sha256):
        raise AnalysisError("EVIDENCE_PROVENANCE_INVALID", "Analysis plan must pin the exact profile source SHA-256.")
    depth = raw.get("depth")
    if depth not in DEPTHS:
        raise AnalysisError("CONTRACT_INVALID", "Analysis depth must be FAST, STANDARD, or DEEP.")
    limits = {"FAST": 4, "STANDARD": 12, "DEEP": 20}
    questions = _text_list(raw.get("questions", []), "questions", maximum=12, item_maximum=500)
    if len(questions) > limits[depth]:
        raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", f"{depth} analysis permits at most {limits[depth]} questions.")
    operations_raw = raw.get("operations", [])
    if not isinstance(operations_raw, list) or len(operations_raw) > limits[depth]:
        raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", f"{depth} analysis permits at most {limits[depth]} deterministic operations.")
    operations = []
    identifiers = set()
    for index, item in enumerate(operations_raw):
        if not isinstance(item, dict) or set(item) - _PLAN_FIELDS:
            raise AnalysisError("CONTRACT_INVALID", f"operations[{index}] has an invalid shape.")
        identifier, operation = item.get("id"), item.get("operation")
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier) or identifier in identifiers:
            raise AnalysisError("CONTRACT_INVALID", f"operations[{index}].id must be a unique valid identifier.")
        if operation not in OPERATIONS:
            raise AnalysisError("CONTRACT_INVALID", f"operations[{index}] uses an unsupported primitive.")
        identifiers.add(identifier)
        result = {"id": identifier, "operation": operation}
        for field in ("column", "period_column", "entity_column", "numerator", "denominator", "x_column", "y_column"):
            if field in item:
                result[field] = _text(item[field], f"operations[{index}].{field}", maximum=240)
        for field in ("columns", "entity_columns"):
            if field in item:
                values = _text_list(item[field], f"operations[{index}].{field}", maximum=3, item_maximum=240)
                if not values or len(values) != len(set(values)):
                    raise AnalysisError("CONTRACT_INVALID", f"operations[{index}].{field} must contain unique column names.")
                result[field] = values
        if "improvement_direction" in item:
            direction = item["improvement_direction"]
            if direction not in {"increase", "decrease"}:
                raise AnalysisError("CONTRACT_INVALID", "improvement_direction must be increase or decrease.")
            result["improvement_direction"] = direction
        for field in ("unit", "numerator_unit", "denominator_unit", "result_unit"):
            if field in item:
                result[field] = _text(item[field], f"operations[{index}].{field}", maximum=80)
        group_by = item.get("group_by", [])
        if not isinstance(group_by, list) or len(group_by) > 2 or any(not isinstance(value, str) or not value.strip() for value in group_by):
            raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", "Each operation may group by at most two dimensions.")
        if len(group_by) != len(set(group_by)):
            raise AnalysisError("CONTRACT_INVALID", "group_by dimensions cannot repeat.")
        result["group_by"] = [value.strip() for value in group_by]
        if "percentile" in item:
            percentile = item["percentile"]
            if isinstance(percentile, bool) or not isinstance(percentile, (int, float)) or not 0 <= percentile <= 100:
                raise AnalysisError("CONTRACT_INVALID", "percentile must be between 0 and 100.")
            result["percentile"] = percentile
        if "limit" in item:
            limit = item["limit"]
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
                raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", "top/bottom limits must be between 1 and 100.")
            result["limit"] = limit
        if "aggregate" in item:
            if item["aggregate"] not in _AGGREGATES:
                raise AnalysisError("CONTRACT_INVALID", "aggregate must be count, sum, mean, median, min, or max.")
            result["aggregate"] = item["aggregate"]
        if operation == "contribution" and result.get("aggregate", "sum") not in {"sum", "count"}:
            raise AnalysisError("CONTRACT_INVALID", "contribution requires an additive sum or non-null count aggregation.")
        if operation == "percentile" and "percentile" not in result:
            raise AnalysisError("CONTRACT_INVALID", "percentile operation requires percentile.")
        if operation in {"top_n", "bottom_n", "rank", "concentration"} and "limit" not in result:
            result["limit"] = 10
        if operation in {"delta", "delta_percent", "delta_percentage_points", "trend", "cohort", "contribution", "composition"}:
            for field in ("period_column",):
                if field not in result:
                    raise AnalysisError("CONTRACT_INVALID", f"{operation} requires {field}.")
        if operation in {"delta", "delta_percent", "delta_percentage_points", "cohort", "contribution", "composition"}:
            if "baseline" not in item or "current" not in item:
                raise AnalysisError("CONTRACT_INVALID", f"{operation} requires baseline and current period values.")
            if isinstance(item["baseline"], (dict, list)) or isinstance(item["current"], (dict, list)):
                raise AnalysisError("CONTRACT_INVALID", f"{operation} period values must be scalar.")
            result["baseline"] = item["baseline"]
            result["current"] = item["current"]
        if operation == "cohort":
            if ("entity_column" in result) == ("entity_columns" in result):
                raise AnalysisError("CONTRACT_INVALID", "cohort requires exactly one of entity_column or entity_columns.")
        elif "entity_column" in result or "entity_columns" in result or "improvement_direction" in result:
            raise AnalysisError("CONTRACT_INVALID", "entity columns and improvement_direction are supported only by cohort.")
        if operation == "ratio" and not {"numerator", "denominator"} <= result.keys():
            raise AnalysisError("CONTRACT_INVALID", "ratio requires numerator and denominator columns.")
        if operation == "ratio":
            if not {"numerator_unit", "denominator_unit", "result_unit"} <= result.keys():
                raise AnalysisError("UNIT_MISMATCH", "ratio requires explicit numerator, denominator, and result units; use 'unknown' when source units are unavailable.")
            expected_unit = ("unknown" if "unknown" in {result["numerator_unit"].casefold(), result["denominator_unit"].casefold()}
                             else "dimensionless" if result["numerator_unit"] == result["denominator_unit"]
                             else f"{result['numerator_unit']}/{result['denominator_unit']}")
            if result["result_unit"] != expected_unit:
                raise AnalysisError("UNIT_MISMATCH", f"ratio result unit must be {expected_unit!r}; implicit unit conversion is not supported.")
        if operation == "delta_percentage_points" and result.get("unit", "").casefold() not in {"%", "percent", "percentage"}:
            raise AnalysisError("UNIT_MISMATCH", "delta_percentage_points requires an explicitly declared percent unit.")
        if operation == "coverage" and "denominator" in result and "column" not in result:
            raise AnalysisError("CONTRACT_INVALID", "coverage with an eligible denominator requires an observed count column.")
        if operation == "correlation" and not {"x_column", "y_column"} <= result.keys():
            raise AnalysisError("CONTRACT_INVALID", "correlation requires x_column and y_column.")
        if operation == "distinct_count":
            if ("column" in result) == ("columns" in result):
                raise AnalysisError("CONTRACT_INVALID", "distinct_count requires exactly one of column or columns.")
        elif operation not in {"count", "ratio", "correlation", "cohort", "composition"} and "column" not in result:
            raise AnalysisError("CONTRACT_INVALID", f"{operation} requires column.")
        if operation in {"share", "top_n", "bottom_n", "rank", "concentration", "contribution", "composition"} and not result["group_by"]:
            raise AnalysisError("CONTRACT_INVALID", f"{operation} requires at least one group_by dimension.")
        operations.append(result)
    budgets = raw.get("budgets", {})
    if not isinstance(budgets, dict) or set(budgets) - {"max_rows", "max_groups"}:
        raise AnalysisError("CONTRACT_INVALID", "budgets supports max_rows and max_groups only.")
    normalized_budgets = {"max_rows": 50000, "max_groups": 100}
    for field, maximum in (("max_rows", 100000), ("max_groups", 100)):
        value = budgets.get(field, normalized_budgets[field])
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", f"budgets.{field} must be between 1 and {maximum}.")
        normalized_budgets[field] = value
    return {
        "schema_version": 1, "source_sha256": source_sha256.lower(), "depth": depth,
        "primary_question": _text(raw.get("primary_question"), "primary_question", maximum=1000),
        "questions": questions, "operations": operations,
        "stop_conditions": _text_list(raw.get("stop_conditions", []), "stop_conditions", maximum=8),
        "budgets": normalized_budgets,
    }


def select_depth(profile: dict[str, Any], *, importance: str = "MEDIUM", requested: str = "AUTO") -> str:
    """Choose a bounded default. The skill may pass an explicit depth from user intent."""
    if requested in DEPTHS:
        return requested
    if requested != "AUTO" or importance not in {"LOW", "MEDIUM", "HIGH"}:
        raise AnalysisError("CONTRACT_INVALID", "Depth must be AUTO, FAST, STANDARD, or DEEP; importance LOW, MEDIUM, or HIGH.")
    rows = profile.get("row_count", 0)
    columns = profile.get("column_count", 0)
    if importance == "HIGH":
        return "DEEP"
    if rows <= 1000 and columns <= 12 and importance == "LOW":
        return "FAST"
    return "STANDARD"
