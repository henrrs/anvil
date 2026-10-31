"""Small deterministic operations over bounded tables; no semantic inference lives here."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from .contracts import validate_analysis_plan
from .errors import AnalysisError
from .profiling import load_rows


MAX_RESULT_BYTES = 5 * 1024 * 1024
MAX_EXPOSED_LABEL_CHARS = 1024


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return _text(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _numeric(values: list[Any], operation: str) -> list[Decimal]:
    result = [_decimal(value) for value in values if value is not None]
    invalid = sum(value is None for value in result)
    numbers = [value for value in result if value is not None]
    if invalid:
        raise AnalysisError("OPERATION_TYPE_MISMATCH", f"{operation} requires numeric values; {invalid} non-numeric value(s) were present.")
    return numbers


def _quantile(values: list[Decimal], percentile: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (Decimal(len(ordered) - 1) * percentile) / Decimal(100)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _aggregate(values: list[Any], operation: str, percentile: Any = 50) -> tuple[str | None, int]:
    present = [value for value in values if value is not None]
    if operation == "count":
        return str(len(present)), len(present)
    if operation == "distinct_count":
        return str(len({_key(value) for value in present})), len(present)
    numbers = _numeric(present, operation)
    if not numbers:
        return None, 0
    with localcontext() as context:
        context.prec = 28
        if operation == "sum":
            value = sum(numbers, Decimal(0))
        elif operation == "mean":
            value = sum(numbers, Decimal(0)) / Decimal(len(numbers))
        elif operation == "median":
            value = _quantile(numbers, Decimal(50))
        elif operation == "percentile":
            value = _quantile(numbers, Decimal(str(percentile)))
        elif operation == "min":
            value = min(numbers)
        elif operation == "max":
            value = max(numbers)
        else:
            raise AnalysisError("CONTRACT_INVALID", f"{operation} is not an aggregation operation.")
    return _text(value), len(numbers)


def _key(value: Any) -> str:
    return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _group_value(row: dict[str, Any], columns: list[str]) -> tuple[Any, ...]:
    return tuple(row.get(name) for name in columns)


def _group_rows(rows: list[dict[str, Any]], columns: list[str], maximum: int) -> list[tuple[tuple[Any, ...], list[dict[str, Any]]]]:
    groups: dict[str, tuple[tuple[Any, ...], list[dict[str, Any]]]] = {}
    if not columns:
        return [((), rows)]
    for row in rows:
        key = _group_value(row, columns)
        encoded = _key(key)
        if encoded not in groups:
            if len(groups) >= maximum:
                raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", f"Grouping exceeded the configured {maximum} group limit.",
                                    remediation="Use a broader segment or request fewer group expansions.")
            groups[encoded] = (key, [])
        groups[encoded][1].append(row)
    return sorted(groups.values(), key=lambda pair: _key(pair[0]))


def _group_label(columns: list[str], values: tuple[Any, ...]) -> dict[str, Any]:
    return {name: _json_value(value) for name, value in zip(columns, values)}


def _records_for_operation(rows: list[dict[str, Any]], operation: dict[str, Any], max_groups: int) -> list[dict[str, Any]]:
    kind = operation["operation"]
    groups = _group_rows(rows, operation.get("group_by", []), max_groups)
    column = operation.get("column")
    output: list[dict[str, Any]] = []
    if kind in {"count", "distinct_count", "sum", "mean", "median", "percentile", "min", "max", "coverage"}:
        for key, part in groups:
            values = [row.get(column) for row in part] if column else [True] * len(part)
            if kind == "coverage":
                if "denominator" in operation:
                    count = sum(_numeric(values, "coverage"), Decimal(0))
                    eligible = sum(_numeric([row.get(operation["denominator"]) for row in part], "coverage"), Decimal(0))
                    output.append({"group": _group_label(operation.get("group_by", []), key),
                                   "covered": _text(count), "eligible": _text(eligible),
                                   "coverage_ratio": _text(count / eligible) if eligible > 0 else None,
                                   "unit": "dimensionless",
                                   "unknown_reason": "eligible denominator is zero or unavailable" if eligible <= 0 else None})
                else:
                    count = sum(value is not None for value in values)
                    output.append({"group": _group_label(operation.get("group_by", []), key),
                                   "covered": count, "eligible": len(values),
                                   "coverage_ratio": _text(Decimal(count) / Decimal(len(values))) if values else None,
                                   "unit": "dimensionless"})
            else:
                value, count = _aggregate(values, kind, operation.get("percentile", 50))
                output.append({"group": _group_label(operation.get("group_by", []), key),
                               "value": value, "unit": operation.get("unit", "unknown"), "observed_count": count})
        return output
    if kind == "distribution":
        for key, part in groups:
            values = [row.get(column) for row in part]
            numbers = [_decimal(value) for value in values if value is not None]
            is_numeric = bool(numbers) and all(value is not None for value in numbers) and all(
                value is None or _decimal(value) is not None for value in values)
            if is_numeric:
                numeric = [value for value in numbers if value is not None]
                p25, p50, p75, p90, p95 = (_quantile(numeric, Decimal(p)) for p in (25, 50, 75, 90, 95))
                iqr = p75 - p25 if p25 is not None and p75 is not None else None
                low_fence = p25 - Decimal("1.5") * iqr if p25 is not None and iqr is not None else None
                high_fence = p75 + Decimal("1.5") * iqr if p75 is not None and iqr is not None else None
                outliers = sum(value < low_fence or value > high_fence for value in numeric) if low_fence is not None and high_fence is not None else 0
                summary = {"count": len(numeric), "min": _text(min(numeric)), "p25": _text(p25),
                           "median": _text(p50), "mean": _text(sum(numeric, Decimal(0)) / len(numeric)),
                           "p75": _text(p75), "p90": _text(p90), "p95": _text(p95), "max": _text(max(numeric)),
                           "iqr": _text(iqr), "outlier_count_1_5_iqr": outliers}
                output.append({"group": _group_label(operation.get("group_by", []), key), "kind": "numeric",
                               "statistics": summary, "unit": operation.get("unit", "unknown"), "row_count": len(part),
                               "unknown_count": sum(value is None for value in values)})
            else:
                counts = Counter(_key(value) for value in values)
                labels = {_key(value): _json_value(value) for value in values}
                output.append({"group": _group_label(operation.get("group_by", []), key), "kind": "categorical",
                               "categories": [{"value": labels[value], "count": count}
                                              for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:operation.get("limit", 10)]],
                               "observed_categories": len(counts), "row_count": len(part)})
        return output
    if kind in {"top_n", "bottom_n", "rank", "concentration", "share"}:
        dimension = operation["group_by"]
        grouped = _group_rows(rows, dimension, max_groups)
        metric_by_key: list[dict[str, Any]] = []
        for key, part in grouped:
            values = [row.get(column) for row in part]
            aggregate, count = _aggregate(values, operation.get("aggregate", "sum"))
            metric_by_key.append({"group": _group_label(dimension, key), "value": aggregate, "unit": operation.get("unit", "unknown"),
                                  "observed_count": count})
        metric_by_key.sort(key=lambda item: (Decimal(item["value"]) if item["value"] is not None else Decimal("-Infinity"),
                                             _key(item["group"])), reverse=kind != "bottom_n")
        total = sum((_decimal(item["value"]) or Decimal(0) for item in metric_by_key), Decimal(0))
        limit = operation.get("limit", 10)
        selected = metric_by_key[:limit]
        if kind in {"top_n", "bottom_n", "rank"}:
            return [{**item, "rank": index + 1} for index, item in enumerate(selected)]
        top_value = sum((_decimal(item["value"]) or Decimal(0) for item in selected), Decimal(0))
        if kind == "share":
            return [{**item, "share": _text((_decimal(item["value"]) or Decimal(0)) / total) if total > 0 else None,
                     "share_unit": "dimensionless"}
                    for item in metric_by_key]
        return [{"top_n": limit, "top_value": _text(top_value), "total_value": _text(total),
                 "top_share": _text(top_value / total) if total > 0 else None,
                 "unit": operation.get("unit", "unknown"), "share_unit": "dimensionless",
                 "groups_included": len(selected), "group_count": len(metric_by_key)}]
    if kind == "ratio":
        for key, part in groups:
            numerator = sum(_numeric([row.get(operation["numerator"]) for row in part], "ratio"), Decimal(0))
            denominator = sum(_numeric([row.get(operation["denominator"]) for row in part], "ratio"), Decimal(0))
            output.append({"group": _group_label(operation.get("group_by", []), key),
                           "numerator": _text(numerator), "denominator": _text(denominator),
                           "value": _text(numerator / denominator) if denominator else None,
                           "unit": operation["result_unit"],
                           "unknown_reason": "zero denominator" if not denominator else None})
        return output
    if kind in {"delta", "delta_percent", "delta_percentage_points"}:
        period_column = operation["period_column"]
        baseline_rows = [row for row in rows if _key(row.get(period_column)) == _key(operation["baseline"])]
        current_rows = [row for row in rows if _key(row.get(period_column)) == _key(operation["current"])]
        base_groups = {_key(key): (key, part) for key, part in _group_rows(baseline_rows, operation.get("group_by", []), max_groups)}
        current_groups = {_key(key): (key, part) for key, part in _group_rows(current_rows, operation.get("group_by", []), max_groups)}
        all_keys = sorted(set(base_groups) | set(current_groups))
        if len(all_keys) > max_groups:
            raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", "Period comparison exceeded the configured group limit.")
        aggregate = operation.get("aggregate", "sum")
        for encoded in all_keys:
            key = (base_groups.get(encoded) or current_groups[encoded])[0]
            before = _aggregate([row.get(column) for row in base_groups[encoded][1]], aggregate)[0] if encoded in base_groups else None
            after = _aggregate([row.get(column) for row in current_groups[encoded][1]], aggregate)[0] if encoded in current_groups else None
            left, right = _decimal(before), _decimal(after)
            delta = right - left if left is not None and right is not None else None
            relative = delta / left * Decimal(100) if delta is not None and left is not None and left > 0 else None
            output.append({"group": _group_label(operation.get("group_by", []), key),
                           "baseline": before, "current": after, "delta": _text(delta),
                           "relative_change": _text(relative),
                           "change_kind": "percentage_points" if kind == "delta_percentage_points" else "relative" if kind == "delta_percent" else "absolute",
                           "relative_change_unit": "percent",
                           "delta_unit": "percentage_points" if kind == "delta_percentage_points" else operation.get("unit", "unknown"),
                           "unknown_reason": "missing comparison period or non-positive/unknown baseline" if delta is None or (kind == "delta_percent" and relative is None) else None})
        return output
    if kind == "trend":
        period_column = operation["period_column"]
        period_groups = _group_rows(rows, [period_column] + operation.get("group_by", []), max_groups)
        agg = operation.get("aggregate", "sum")
        by_segment: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for key, part in period_groups:
            period = key[0]
            segment_columns = operation.get("group_by", [])
            segment = key[1:]
            value, count = _aggregate([row.get(column) for row in part], agg)
            by_segment[_key(segment)].append({"period": _json_value(period), "group": _group_label(segment_columns, segment),
                                              "value": value, "observed_count": count})
        for points in by_segment.values():
            points.sort(key=lambda item: str(item["period"]))
            enough = len(points) >= 3
            first, last = _decimal(points[0]["value"]), _decimal(points[-1]["value"])
            output.append({"group": points[0]["group"], "points": points, "point_count": len(points),
                           "endpoint_change": _text(last - first) if len(points) >= 2 and first is not None and last is not None else None,
                           "unit": operation.get("unit", "unknown"),
                           "trend_supported": enough,
                           "warning": None if enough else "Two observations support a change comparison, not a trend." if len(points) == 2 else "Insufficient temporal observations to assess a trend."})
        return output
    if kind == "volatility":
        for key, part in groups:
            values = _numeric([row.get(column) for row in part], "volatility")
            mean = sum(values, Decimal(0)) / len(values) if values else None
            variance = (sum(((value - mean) ** 2 for value in values), Decimal(0)) / len(values)) if values and mean is not None else None
            with localcontext() as context:
                context.prec = 28
                deviation = variance.sqrt() if variance is not None else None
            output.append({"group": _group_label(operation.get("group_by", []), key), "count": len(values),
                           "mean": _text(mean), "population_standard_deviation": _text(deviation),
                           "unit": operation.get("unit", "unknown"),
                           "min": _text(min(values)) if values else None, "max": _text(max(values)) if values else None})
        return output
    if kind == "cohort":
        entity, period = operation["entity_column"], operation["period_column"]
        baseline, current = operation["baseline"], operation["current"]
        sides: dict[Any, dict[str, list[Any]]] = defaultdict(lambda: {"baseline": [], "current": []})
        for row in rows:
            target = "baseline" if _key(row.get(period)) == _key(baseline) else "current" if _key(row.get(period)) == _key(current) else None
            if target:
                sides[row.get(entity)][target].append(row.get(column) if column else 1)
        old = {value for value, part in sides.items() if value is not None and part["baseline"]}
        new = {value for value, part in sides.items() if value is not None and part["current"]}
        common = old & new
        agg = operation.get("aggregate", "sum")
        common_base = [value for entity_id in common for value in sides[entity_id]["baseline"]]
        common_now = [value for entity_id in common for value in sides[entity_id]["current"]]
        base_value = _aggregate(common_base, agg)[0] if common_base else None
        current_value = _aggregate(common_now, agg)[0] if common_now else None
        output.append({"eligible_baseline": len(old), "eligible_current": len(new),
                       "common_entities": len(common), "added_entities": len(new - old), "removed_entities": len(old - new),
                       "like_for_like_baseline": base_value, "like_for_like_current": current_value,
                       "like_for_like_delta": _text((_decimal(current_value) - _decimal(base_value))) if base_value is not None and current_value is not None else None,
                       "unit": operation.get("unit", "unknown"), "aggregation": agg})
        return output
    if kind == "correlation":
        pairs = [(_decimal(row.get(operation["x_column"])), _decimal(row.get(operation["y_column"]))) for row in rows]
        valid = [(x, y) for x, y in pairs if x is not None and y is not None]
        correlation = None
        if len(valid) >= 3:
            with localcontext() as context:
                context.prec = 28
                count = Decimal(len(valid))
                mean_x = sum((x for x, _ in valid), Decimal(0)) / count
                mean_y = sum((y for _, y in valid), Decimal(0)) / count
                covariance = sum(((x - mean_x) * (y - mean_y) for x, y in valid), Decimal(0))
                square_x = sum(((x - mean_x) ** 2 for x, _ in valid), Decimal(0))
                square_y = sum(((y - mean_y) ** 2 for _, y in valid), Decimal(0))
                if square_x and square_y:
                    correlation = covariance / (square_x * square_y).sqrt()
        output.append({"x_column": operation["x_column"], "y_column": operation["y_column"],
                       "paired_count": len(valid), "pearson_r": _text(correlation),
                       "interpretation": "association only; correlation does not establish causation",
                       "unknown_reason": "fewer than three valid pairs or no variation" if correlation is None else None})
        return output
    raise AnalysisError("CONTRACT_INVALID", f"Unsupported operation {kind}.")


def execute_plan(path: str, raw_plan: Any) -> dict[str, Any]:
    plan = validate_analysis_plan(raw_plan)
    rows, metadata = load_rows(path, max_rows=plan["budgets"]["max_rows"])
    if plan["source_sha256"] != metadata["source"]["sha256"]:
        raise AnalysisError("INPUT_SOURCE_CHANGED", "The analysis plan was compiled against a different source profile hash.",
                            remediation="Reprofile the current input and regenerate the bounded plan.")
    if metadata["truncated"]:
        raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", f"Input has {metadata['row_count']} rows; the plan budget is {plan['budgets']['max_rows']}.",
                            remediation="Raise the explicit max_rows budget up to 100000 or use a narrower/pre-aggregated extract.")
    available = set(metadata["columns"])
    for operation in plan["operations"]:
        references = {value for key, value in operation.items()
                      if key in {"column", "period_column", "entity_column", "numerator", "denominator", "x_column", "y_column"}}
        references.update(operation.get("group_by", []))
        missing = references - available
        if missing:
            raise AnalysisError("PLAN_COLUMN_UNKNOWN", "Plan refers to columns absent from the input: " + ", ".join(sorted(missing)) + ".")
        exposed = set(operation.get("group_by", []))
        if operation["operation"] == "distribution":
            exposed.add(operation["column"])
        if operation["operation"] in {"top_n", "bottom_n", "rank", "concentration", "share"}:
            exposed.update(operation["group_by"])
        for name in exposed:
            if any(isinstance(row.get(name), str) and len(row[name]) > MAX_EXPOSED_LABEL_CHARS for row in rows):
                raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", f"Column {name!r} contains labels too long to safely include in bounded group output.",
                                    remediation="Use a normalized/categorical key or analyze a narrower extract.")
    results = []
    for operation in plan["operations"]:
        results.append({"id": operation["id"], "operation": operation["operation"],
                        "question": plan["primary_question"],
                        "results": _records_for_operation(rows, operation, plan["budgets"]["max_groups"])})
    result = {
        "schema_version": 1, "depth": plan["depth"], "primary_question": plan["primary_question"],
        "source": metadata["source"], "profile": {"row_count": metadata["row_count"],
        "analyzed_rows": len(rows), "column_count": len(metadata["columns"]), "complete": True},
        "questions": plan["questions"], "operations": results, "stop_conditions": plan["stop_conditions"],
        "limits": plan["budgets"],
        "notes": ["Exploration stopped after the bounded plan; no unrequested source or segment expansion was performed."],
    }
    if len(json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")) > MAX_RESULT_BYTES:
        raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", "The deterministic result exceeds the 5 MiB output limit.",
                            remediation="Reduce grouped operations, group limits, or the number of planned operations.")
    return result
