"""Small deterministic operations over bounded tables; no semantic inference lives here."""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from .contracts import validate_analysis_plan
from .errors import AnalysisError
from .profiling import load_rows
from .semantic import infer_semantic_context, validate_semantic_context
from .statistics import compare_values, distribution_statistics, quantile


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
            value = quantile(numbers, 50)
        elif operation == "percentile":
            value = quantile(numbers, percentile)
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
            if kind == "distinct_count" and operation.get("columns"):
                values = [tuple(row.get(name) for name in operation["columns"]) for row in part]
            else:
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
                statistics = distribution_statistics(numeric)
                assert statistics is not None
                summary = {"count": statistics["count"], "min": statistics["min"],
                           "p25": statistics["q1"], "median": statistics["median"],
                           "mean": statistics["mean"], "p75": statistics["q3"],
                           "p90": statistics["p90"], "p95": statistics["p95"],
                           "max": statistics["max"], "iqr": statistics["iqr"],
                           "outlier_count_1_5_iqr": statistics["outlier_count"]}
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
    if kind in {"delta", "delta_percent", "delta_percentage_points", "contribution"}:
        period_column = operation["period_column"]
        baseline_rows = [row for row in rows if _key(row.get(period_column)) == _key(operation["baseline"])]
        current_rows = [row for row in rows if _key(row.get(period_column)) == _key(operation["current"])]
        base_groups = {_key(key): (key, part) for key, part in _group_rows(baseline_rows, operation.get("group_by", []), max_groups)}
        current_groups = {_key(key): (key, part) for key, part in _group_rows(current_rows, operation.get("group_by", []), max_groups)}
        all_keys = sorted(set(base_groups) | set(current_groups))
        if len(all_keys) > max_groups:
            raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", "Period comparison exceeded the configured group limit.")
        aggregate = operation.get("aggregate", "sum")
        if kind == "contribution":
            total_delta = Decimal(0)
            deltas: list[dict[str, Any]] = []
            incomplete = False
            aggregate = operation.get("aggregate", "sum")
            for encoded in all_keys:
                key = (base_groups.get(encoded) or current_groups[encoded])[0]
                base_part = base_groups.get(encoded)
                current_part = current_groups.get(encoded)
                before = (_aggregate([row.get(column) for row in base_part[1]], aggregate)[0]
                          if base_part else "0")
                after = (_aggregate([row.get(column) for row in current_part[1]], aggregate)[0]
                         if current_part else "0")
                left, right = _decimal(before), _decimal(after)
                delta = right - left if left is not None and right is not None else None
                if delta is None:
                    incomplete = True
                else:
                    total_delta += delta
                deltas.append({"group": _group_label(operation.get("group_by", []), key),
                               "baseline": before, "current": after, "delta": _text(delta),
                               "unit": operation.get("unit", "unknown")})
            absolute_total = sum((abs(_decimal(item["delta"]) or Decimal(0)) for item in deltas), Decimal(0))
            deltas.sort(key=lambda item: (abs(_decimal(item["delta"]) or Decimal(0)), _key(item["group"])), reverse=True)
            for item in deltas:
                delta = _decimal(item["delta"])
                item["share_of_net_change"] = _text(delta / total_delta) if delta is not None and total_delta else None
                item["share_of_absolute_change"] = _text(abs(delta) / absolute_total) if delta is not None and absolute_total else None
                item["unknown_reason"] = ("some grouped values were missing" if delta is None else
                                           "net change is zero" if not total_delta else None)
            return [{"groups": deltas, "total_delta": _text(total_delta) if not incomplete else None,
                     "known_group_delta": _text(total_delta), "absolute_group_delta": _text(absolute_total),
                     "group_count": len(deltas), "aggregation": aggregate,
                     "complete": not incomplete,
                     "warning": ("At least one group had a missing metric value; total contribution is incomplete." if incomplete else
                                 "Signed contribution shares may exceed 100% in magnitude when groups offset each other.") if incomplete or any(
                                     abs(_decimal(item["share_of_net_change"]) or Decimal(0)) > 1 for item in deltas) else None}]

        for encoded in all_keys:
            key = (base_groups.get(encoded) or current_groups[encoded])[0]
            before = _aggregate([row.get(column) for row in base_groups[encoded][1]], aggregate)[0] if encoded in base_groups else None
            after = _aggregate([row.get(column) for row in current_groups[encoded][1]], aggregate)[0] if encoded in current_groups else None
            left, right = _decimal(before), _decimal(after)
            comparison = compare_values(left, right)
            delta = _decimal(comparison["absolute_change"])
            relative = _decimal(comparison["relative_change"])
            output.append({"group": _group_label(operation.get("group_by", []), key),
                           "baseline": before, "current": after, "delta": _text(delta),
                           "relative_change": _text(relative),
                           "change_kind": "percentage_points" if kind == "delta_percentage_points" else "relative" if kind == "delta_percent" else "absolute",
                           "relative_change_unit": "percent",
                           "delta_unit": "percentage_points" if kind == "delta_percentage_points" else operation.get("unit", "unknown"),
                           "unknown_reason": "missing comparison period or non-positive/unknown baseline" if delta is None or (kind == "delta_percent" and relative is None) else None})
        return output
    if kind == "composition":
        period_column = operation["period_column"]
        baseline_rows = [row for row in rows if _key(row.get(period_column)) == _key(operation["baseline"])]
        current_rows = [row for row in rows if _key(row.get(period_column)) == _key(operation["current"])]
        dimensions = operation["group_by"]
        baseline_groups = {_key(key): (key, part) for key, part in _group_rows(baseline_rows, dimensions, max_groups)}
        current_groups = {_key(key): (key, part) for key, part in _group_rows(current_rows, dimensions, max_groups)}
        all_keys = sorted(set(baseline_groups) | set(current_groups))
        if len(all_keys) > max_groups:
            raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", "Composition comparison exceeded the configured group limit.")
        metric_column = operation.get("column")
        aggregate = operation.get("aggregate", "mean")
        baseline_total, current_total = len(baseline_rows), len(current_rows)
        details = []
        total_variation = Decimal(0)
        for encoded in all_keys:
            key = (baseline_groups.get(encoded) or current_groups[encoded])[0]
            old_part = baseline_groups.get(encoded, (None, []))[1]
            new_part = current_groups.get(encoded, (None, []))[1]
            old_share = Decimal(len(old_part)) / baseline_total if baseline_total else None
            new_share = Decimal(len(new_part)) / current_total if current_total else None
            share_delta = new_share - old_share if old_share is not None and new_share is not None else None
            if share_delta is not None:
                total_variation += abs(share_delta)
            old_metric, new_metric = None, None
            old_metric_count, new_metric_count = None, None
            metric_delta = None
            if metric_column:
                old_metric, old_metric_count = _aggregate([row.get(metric_column) for row in old_part], aggregate) if old_part else (None, 0)
                new_metric, new_metric_count = _aggregate([row.get(metric_column) for row in new_part], aggregate) if new_part else (None, 0)
                old_value, new_value = _decimal(old_metric), _decimal(new_metric)
                metric_delta = _text(new_value - old_value) if old_value is not None and new_value is not None else None
            details.append({"group": _group_label(dimensions, key),
                            "baseline_count": len(old_part), "current_count": len(new_part),
                            "baseline_share": _text(old_share), "current_share": _text(new_share),
                            "share_delta": _text(share_delta), "share_delta_unit": "proportion",
                            "baseline_metric_count": old_metric_count, "current_metric_count": new_metric_count,
                            "metric_baseline": old_metric, "metric_current": new_metric,
                            "metric_delta": metric_delta, "metric_unit": operation.get("unit", "unknown")})
        overall_old, overall_new, overall_delta = None, None, None
        overall_old_count, overall_new_count = None, None
        if metric_column:
            overall_old, overall_old_count = _aggregate([row.get(metric_column) for row in baseline_rows], aggregate) if baseline_rows else (None, 0)
            overall_new, overall_new_count = _aggregate([row.get(metric_column) for row in current_rows], aggregate) if current_rows else (None, 0)
            old_value, new_value = _decimal(overall_old), _decimal(overall_new)
            overall_delta = _text(new_value - old_value) if old_value is not None and new_value is not None else None
        return [{"baseline_period": _json_value(operation["baseline"]), "current_period": _json_value(operation["current"]),
                 "baseline_observation_count": baseline_total, "current_observation_count": current_total,
                 "groups": details,
                 "composition_shift": _text(total_variation / 2) if baseline_total and current_total else None,
                 "composition_shift_unit": "proportion of population mass",
                 "overall_metric_baseline": overall_old, "overall_metric_current": overall_new,
                 "overall_metric_delta": overall_delta, "metric_aggregate": aggregate if metric_column else None,
                 "overall_baseline_metric_count": overall_old_count, "overall_current_metric_count": overall_new_count,
                 "metric_unit": operation.get("unit", "unknown"),
                 "warning": "Share movement is descriptive composition evidence; it does not establish causality or decompose the aggregate metric."}]
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
        entity_fields = operation.get("entity_columns") or [operation["entity_column"]]
        period = operation["period_column"]
        baseline, current = operation["baseline"], operation["current"]
        sides: dict[str, dict[str, list[Any]]] = defaultdict(lambda: {"baseline": [], "current": []})
        unkeyed_rows = 0
        for row in rows:
            target = "baseline" if _key(row.get(period)) == _key(baseline) else "current" if _key(row.get(period)) == _key(current) else None
            entity_values = tuple(row.get(field) for field in entity_fields)
            if target and any(value is None for value in entity_values):
                unkeyed_rows += 1
                continue
            if target:
                key = _key(entity_values)
                sides[key][target].append(row.get(column) if column else 1)
        old = {value for value, part in sides.items() if part["baseline"]}
        new = {value for value, part in sides.items() if part["current"]}
        common = old & new
        agg = operation.get("aggregate", "sum")
        per_entity: dict[str, dict[str, str | None]] = {}
        for entity_id in common:
            before, _ = _aggregate(sides[entity_id]["baseline"], agg)
            after, _ = _aggregate(sides[entity_id]["current"], agg)
            per_entity[entity_id] = {"baseline": before, "current": after}
        measured = [(entity_id, _decimal(values["baseline"]), _decimal(values["current"]))
                    for entity_id, values in per_entity.items()]
        comparable = [(entity_id, before, after) for entity_id, before, after in measured
                      if before is not None and after is not None]
        common_base = [before for _, before, _ in comparable]
        common_now = [after for _, _, after in comparable]
        base_value, _ = _aggregate(common_base, agg) if common_base else (None, 0)
        current_value, _ = _aggregate(common_now, agg) if common_now else (None, 0)
        increases = sum(after > before for _, before, after in comparable)
        decreases = sum(after < before for _, before, after in comparable)
        unchanged = len(comparable) - increases - decreases
        improvement_direction = operation.get("improvement_direction")
        improved = increases if improvement_direction == "increase" else decreases if improvement_direction == "decrease" else None
        worsened = decreases if improvement_direction == "increase" else increases if improvement_direction == "decrease" else None
        comparison = compare_values(base_value, current_value)
        output.append({"eligible_baseline": len(old), "eligible_current": len(new),
                       "common_entities": len(common), "added_entities": len(new - old), "removed_entities": len(old - new),
                       "like_for_like_baseline": base_value, "like_for_like_current": current_value,
                       "like_for_like_delta": comparison["absolute_change"],
                       "comparable_entities": len(comparable), "unavailable_entity_comparisons": len(common) - len(comparable),
                       "increased_entities": increases, "decreased_entities": decreases,
                       "unchanged_entities": unchanged,
                       "improved_entities": improved, "worsened_entities": worsened,
                       "improvement_direction": improvement_direction,
                       "improved_share": _text(Decimal(improved) / len(comparable)) if improved is not None and comparable else None,
                       "entity_key_fields": entity_fields,
                       "entity_count_basis": "distinct_key" if len(entity_fields) == 1 else "distinct_composite_key",
                       "unkeyed_rows": unkeyed_rows,
                       "unit": operation.get("unit", "unknown"), "aggregation": agg,
                       "warning": "Entity-level values were aggregated within each entity-period before cohort comparison."})
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


def execute_plan(path: str, raw_plan: Any, *, profile: Any = None) -> dict[str, Any]:
    started = time.perf_counter()
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
        references.update(operation.get("columns", []))
        references.update(operation.get("entity_columns", []))
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
    semantic_reused = False
    semantic_context = None
    if profile is not None:
        if not isinstance(profile, dict) or not isinstance(profile.get("source"), dict):
            raise AnalysisError("CONTRACT_INVALID", "A reused profile must include source provenance.")
        if (profile["source"].get("sha256") != metadata["source"]["sha256"]
                or profile["source"].get("locator") != metadata["source"]["locator"]):
            raise AnalysisError("EVIDENCE_PROVENANCE_INVALID", "Reused profile does not match the executed source path and content hash.")
        if profile.get("row_count") != metadata["row_count"]:
            raise AnalysisError("EVIDENCE_PROVENANCE_INVALID", "Reused profile row count does not match the executed source.")
        if profile.get("semantic_context") is not None:
            semantic_context = validate_semantic_context(profile["semantic_context"], known_columns=available)
            if (semantic_context["observations"]["count"] != metadata["row_count"]
                    or not semantic_context["observations"]["complete"]):
                raise AnalysisError("EVIDENCE_PROVENANCE_INVALID", "Reused semantic context is incomplete or does not match the current source.")
            semantic_reused = True
    if semantic_context is None:
        semantic_context = infer_semantic_context(rows, metadata["columns"], total_rows=metadata["row_count"],
                                                 complete=True, depth=plan["depth"])
    execution_metadata = {
        "analysis_mode": plan["depth"], "datasets_inspected": 1, "rows_scanned": len(rows),
        "operations_evaluated": len(results), "hypotheses_evaluated": 0, "findings_produced": 0,
        "model_calls": 0, "semantic_profile_reused": semantic_reused,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    limitations = ["The deterministic helper calculates evidence but does not assign business meaning or generate findings.",
                   "Entity and grain fields are evidence-backed candidates; confirm them against the original question and source semantics."]
    analysis_result = {
        "schema_version": 1,
        "analysis_context": semantic_context,
        "metrics": results,
        "findings": [],
        "claims": [],
        "warnings": [],
        "limitations": limitations,
        "provenance": {"source": metadata["source"], "plan_source_sha256": plan["source_sha256"]},
        "execution_metadata": execution_metadata,
    }
    result = {
        "schema_version": 1, "depth": plan["depth"], "primary_question": plan["primary_question"],
        "source": metadata["source"], "profile": {"row_count": metadata["row_count"],
        "analyzed_rows": len(rows), "column_count": len(metadata["columns"]), "complete": True},
        "questions": plan["questions"], "operations": results, "stop_conditions": plan["stop_conditions"],
        "limits": plan["budgets"], "semantic_context": semantic_context,
        "execution_metadata": execution_metadata, "analysis_result": analysis_result,
        "notes": ["Exploration stopped after the bounded plan; no unrequested source or segment expansion was performed."],
    }
    if len(json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")) > MAX_RESULT_BYTES:
        raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", "The deterministic result exceeds the 5 MiB output limit.",
                            remediation="Reduce grouped operations, group limits, or the number of planned operations.")
    return result
