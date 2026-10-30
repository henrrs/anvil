"""Deterministic quantitative analysis; no narrative or renderer decisions live here."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Any

from .contracts import EPISTEMIC_TYPES, IDENTIFIER, decimal_value
from .errors import CommunicationError


DEFAULT_NEAR_ZERO = Decimal("1e-12")
SUPPORTED_DIRECTION = {"lower_is_better", "higher_is_better", "neutral", "unknown"}


def _derived_epistemic(baseline: dict[str, Any] | None, current: dict[str, Any] | None) -> str:
    if not baseline or not current or baseline.get("value") is None or current.get("value") is None:
        return "UNKNOWN"
    states = {baseline.get("epistemic", "MEASUREMENT"), current.get("epistemic", "MEASUREMENT")}
    for state in ("UNKNOWN", "ASSUMPTION", "SCENARIO", "ESTIMATE", "PROJECTION", "PROPOSAL", "INFERRED", "INFERENCE"):
        if state in states:
            return state
    return "DERIVED_VALUE"


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _observation(value: Any, *, field: str, default_unit: str, evidence_ids: list[str] | None = None,
                 period: str | None = None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CommunicationError("CONTRACT_INVALID", f"{field} must be an object or null.")
    raw = value.get("value")
    unit = value.get("unit", default_unit)
    if not isinstance(unit, str) or not unit.strip() or len(unit) > 80:
        raise CommunicationError("UNIT_MISMATCH", f"{field}.unit is required.")
    refs = value.get("evidence_ids", evidence_ids or [])
    if not isinstance(refs, list) or any(not isinstance(ref, str) or not IDENTIFIER.fullmatch(ref) for ref in refs):
        raise CommunicationError("CONTRACT_INVALID", f"{field}.evidence_ids must be a list of IDs.")
    if len(refs) != len(set(refs)):
        raise CommunicationError("CONTRACT_INVALID", f"{field}.evidence_ids contains duplicate IDs.")
    epistemic = value.get("epistemic", "MEASUREMENT")
    if not isinstance(epistemic, str) or epistemic not in EPISTEMIC_TYPES:
        raise CommunicationError("CONTRACT_INVALID", f"{field}.epistemic is not a valid observation type.")
    observation_period = value.get("period", period)
    if observation_period is not None and (not isinstance(observation_period, str) or len(observation_period) > 240):
        raise CommunicationError("CONTRACT_INVALID", f"{field}.period must be short text or null.")
    parsed = None if raw is None else decimal_value(raw, field=f"{field}.value")
    return {"value": _decimal_text(parsed), "unit": unit.strip(),
            "period": observation_period, "evidence_ids": list(refs),
            "epistemic": epistemic}


def _direction(change: Decimal | None) -> str:
    if change is None:
        return "unknown"
    return "increase" if change > 0 else "decrease" if change < 0 else "unchanged"


def _interpretation(direction: str, semantics: str) -> str:
    if direction == "unknown" or semantics == "unknown":
        return "unknown"
    if direction == "unchanged" or semantics == "neutral":
        return "neutral"
    favorable = ((direction == "decrease" and semantics == "lower_is_better")
                 or (direction == "increase" and semantics == "higher_is_better"))
    return "favorable" if favorable else "unfavorable"


def _relative_change(baseline: Decimal | None, change: Decimal | None, threshold: Decimal) -> Decimal | None:
    # A signed or zero baseline does not have an unambiguous relative-change denominator.
    if baseline is None or change is None or baseline <= threshold:
        return None
    with localcontext() as context:
        context.prec = 28
        return change / baseline * Decimal(100)


def analyze_metric(metric: Any) -> dict[str, Any]:
    if not isinstance(metric, dict):
        raise CommunicationError("CONTRACT_INVALID", "Each metric must be an object.")
    identifier = metric.get("id")
    name = metric.get("name")
    unit = metric.get("unit")
    kind = metric.get("kind", "amount")
    semantics = metric.get("semantics", "unknown")
    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier) or not isinstance(name, str) or not name.strip() or len(name) > 240:
        raise CommunicationError("CONTRACT_INVALID", "Each metric needs a stable ID and name.")
    if not isinstance(unit, str) or not unit.strip() or len(unit) > 80:
        raise CommunicationError("UNIT_MISMATCH", f"Metric {identifier} must declare a unit.")
    if not isinstance(kind, str) or kind not in {"amount", "rate", "duration", "count", "ratio", "other"}:
        raise CommunicationError("CONTRACT_INVALID", f"Metric {identifier} has an unsupported kind.")
    if not isinstance(semantics, str) or semantics not in SUPPORTED_DIRECTION:
        raise CommunicationError("CONTRACT_INVALID", f"Metric {identifier} semantics must be explicit or unknown.")
    confidence = metric.get("confidence", "UNKNOWN")
    if not isinstance(confidence, str) or confidence not in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
        raise CommunicationError("CONTRACT_INVALID", f"Metric {identifier} has an invalid confidence level.")
    threshold = decimal_value(metric.get("near_zero_threshold", DEFAULT_NEAR_ZERO),
                              field=f"{identifier}.near_zero_threshold")
    if threshold < 0:
        raise CommunicationError("CONTRACT_INVALID", "near_zero_threshold cannot be negative.")
    baseline_semantics = metric.get("baseline_semantics")
    if baseline_semantics is not None and (not isinstance(baseline_semantics, str) or not baseline_semantics.strip() or len(baseline_semantics) > 240):
        raise CommunicationError("CONTRACT_INVALID", f"Metric {identifier} baseline_semantics must be short text or null.")
    baseline = _observation(metric.get("baseline"), field=f"{identifier}.baseline", default_unit=unit,
                           evidence_ids=metric.get("evidence_ids", []))
    current = _observation(metric.get("current"), field=f"{identifier}.current", default_unit=unit,
                           evidence_ids=metric.get("evidence_ids", []))
    for label, value in (("baseline", baseline), ("current", current)):
        if value is not None and value["unit"] != unit:
            raise CommunicationError("UNIT_MISMATCH", f"Metric {identifier} {label} unit does not match {unit}.")
    base_value = decimal_value(baseline["value"], field=f"{identifier}.baseline.value") if baseline and baseline["value"] is not None else None
    current_value = decimal_value(current["value"], field=f"{identifier}.current.value") if current and current["value"] is not None else None
    change = current_value - base_value if current_value is not None and base_value is not None else None
    relative = _relative_change(base_value, change, threshold)
    rate_unit = unit.casefold() in {"%", "percent", "percentage"}
    pp_change = change if kind == "rate" and rate_unit else None
    direction = _direction(change)
    epistemic = _derived_epistemic(baseline, current)
    warnings: list[str] = []
    if base_value is not None and change is not None and relative is None:
        warnings.append("Relative change is not meaningful for a zero, near-zero, or negative baseline; absolute change is preserved.")
    if base_value is None or current_value is None:
        warnings.append("A baseline or current measurement is unavailable; it was not substituted with zero.")
    projection = None
    projection_request = metric.get("annualize")
    if projection_request is not None:
        if not isinstance(projection_request, dict):
            raise CommunicationError("CONTRACT_INVALID", f"Metric {identifier} annualize must be an object.")
        days = decimal_value(projection_request.get("period_days"), field=f"{identifier}.annualize.period_days")
        assumption = projection_request.get("assumption")
        if days <= 0 or not isinstance(assumption, str) or not assumption.strip() or len(assumption) > 1000:
            raise CommunicationError("QUANTITATIVE_ANALYSIS_INVALID", "Annualization requires a positive observed period and an explicit persistence assumption.")
        if change is None:
            warnings.append("Annualized projection was omitted because both comparison measurements are not available.")
        else:
            with localcontext() as context:
                context.prec = 28
                projected = change * Decimal(365) / days
            projection = {"value": _decimal_text(projected), "unit": unit,
                          "period": "365 days", "epistemic": "PROJECTION",
                          "basis_period_days": _decimal_text(days), "assumption": assumption.strip()}
            if days < 30:
                warnings.append("Projection is extrapolated from fewer than 30 observed days and needs strong qualification.")

    result: dict[str, Any] = {
        "id": identifier, "metric": name.strip(), "kind": kind, "unit": unit.strip(),
        "semantics": semantics,
        "baseline": baseline, "current": current,
        "absolute_change": _decimal_text(change), "relative_change": _decimal_text(relative),
        "percentage_point_change": _decimal_text(pp_change), "direction": direction,
        "interpretation": "unknown" if epistemic == "UNKNOWN" else _interpretation(direction, semantics),
        "epistemic": epistemic,
        "confidence": confidence,
        "baseline_semantics": baseline_semantics,
        "warnings": warnings,
    }
    if projection is not None:
        result["projection"] = projection
    normalization = metric.get("normalization")
    if normalization is not None:
        result["normalization"] = _normalize(identifier, unit, baseline, current, normalization, threshold)
    return result


def _normalize(identifier: str, unit: str, baseline: dict[str, Any] | None,
               current: dict[str, Any] | None, config: Any, threshold: Decimal) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise CommunicationError("CONTRACT_INVALID", f"Metric {identifier} normalization must be an object.")
    name = config.get("name")
    result_unit = config.get("unit")
    denominator_unit = config.get("denominator_unit")
    if not all(isinstance(value, str) and value.strip() and len(value) <= 240 for value in (name, result_unit, denominator_unit)):
        raise CommunicationError("UNIT_MISMATCH", f"Metric {identifier} normalization requires a name and numerator/denominator units.")
    expected_unit = f"{unit.strip()}/{denominator_unit.strip()}"
    if result_unit.strip() != expected_unit:
        raise CommunicationError("UNIT_MISMATCH", f"Normalized unit must be declared as {expected_unit}; implicit unit conversions are not supported.")
    allowed = {"name", "unit", "denominator_unit", "baseline_denominator", "current_denominator",
               "baseline_denominator_evidence_ids", "current_denominator_evidence_ids"}
    if set(config) - allowed:
        raise CommunicationError("CONTRACT_INVALID", f"Metric {identifier} normalization has unsupported fields.")
    baseline_denominator = config.get("baseline_denominator")
    current_denominator = config.get("current_denominator")
    baseline_refs = config.get("baseline_denominator_evidence_ids", [])
    current_refs = config.get("current_denominator_evidence_ids", [])
    for label, refs in (("baseline", baseline_refs), ("current", current_refs)):
        if not isinstance(refs, list) or any(not isinstance(ref, str) or not IDENTIFIER.fullmatch(ref) for ref in refs):
            raise CommunicationError("CONTRACT_INVALID", f"{identifier} normalization {label} denominator evidence IDs must be a list.")
        if len(refs) != len(set(refs)):
            raise CommunicationError("CONTRACT_INVALID", f"{identifier} normalization {label} denominator evidence IDs are duplicated.")
    if baseline_denominator is not None and not baseline_refs:
        raise CommunicationError("EVIDENCE_INSUFFICIENT", f"{identifier} normalization baseline denominator needs a supporting evidence ID.")
    if current_denominator is not None and not current_refs:
        raise CommunicationError("EVIDENCE_INSUFFICIENT", f"{identifier} normalization current denominator needs a supporting evidence ID.")
    values: dict[str, Decimal | None] = {}
    for label, amount, denominator in (("baseline", baseline, baseline_denominator), ("current", current, current_denominator)):
        if amount is None or amount.get("value") is None or denominator is None:
            values[label] = None
            continue
        divisor = decimal_value(denominator, field=f"{identifier}.normalization.{label}_denominator")
        if divisor <= 0:
            raise CommunicationError("QUANTITATIVE_ANALYSIS_INVALID", "A normalization denominator must be greater than zero.")
        numerator = decimal_value(amount["value"], field=f"{identifier}.{label}.value")
        values[label] = numerator / divisor
    baseline_value, current_value = values["baseline"], values["current"]
    change = current_value - baseline_value if current_value is not None and baseline_value is not None else None
    relative = _relative_change(baseline_value, change, threshold)
    return {
        "name": name.strip(), "unit": result_unit.strip(), "numerator_unit": unit,
        "denominator_unit": denominator_unit.strip(),
        "baseline_denominator": (str(baseline_denominator) if baseline_denominator is not None else None),
        "current_denominator": (str(current_denominator) if current_denominator is not None else None),
        "baseline_denominator_evidence_ids": list(dict.fromkeys(baseline_refs)),
        "current_denominator_evidence_ids": list(dict.fromkeys(current_refs)),
        "baseline": _decimal_text(baseline_value), "current": _decimal_text(current_value),
        "absolute_change": _decimal_text(change), "relative_change": _decimal_text(relative),
        "epistemic": _derived_epistemic(baseline, current) if change is not None else "UNKNOWN",
    }


def _quantile(values: list[Decimal], probability: Decimal) -> Decimal:
    if len(values) == 1:
        return values[0]
    position = Decimal(len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] * (Decimal(1) - fraction) + values[upper] * fraction


def distribution_summary(values: Any, *, unit: str, exclusions: Any = None,
                         epistemic: str = "MEASUREMENT") -> dict[str, Any]:
    if not isinstance(values, list) or len(values) > 100_000:
        raise CommunicationError("CONTRACT_INVALID", "Distribution values must be a list containing at most 100000 entries.")
    if not isinstance(unit, str) or not unit.strip() or len(unit) > 80:
        raise CommunicationError("UNIT_MISMATCH", "Distribution unit is required.")
    if not isinstance(epistemic, str) or epistemic not in EPISTEMIC_TYPES:
        raise CommunicationError("CONTRACT_INVALID", "Distribution epistemic status is invalid.")
    exclusion_map: dict[int, str] = {}
    if exclusions is not None:
        if not isinstance(exclusions, list) or len(exclusions) > len(values):
            raise CommunicationError("CONTRACT_INVALID", "Distribution exclusions must be a bounded list.")
        for item in exclusions:
            if not isinstance(item, dict) or not isinstance(item.get("index"), int) or isinstance(item.get("index"), bool) or not isinstance(item.get("reason"), str) or not item["reason"].strip():
                raise CommunicationError("CONTRACT_INVALID", "Each exclusion needs a zero-based index and explicit reason.")
            if item["index"] < 0 or item["index"] >= len(values) or item["index"] in exclusion_map:
                raise CommunicationError("CONTRACT_INVALID", "Distribution exclusion index is invalid or duplicated.")
            exclusion_map[item["index"]] = item["reason"].strip()
    included: list[Decimal] = []
    excluded: list[dict[str, Any]] = []
    counts: Counter[Decimal] = Counter()
    missing = 0
    for index, raw in enumerate(values):
        if raw is None:
            if index in exclusion_map:
                raise CommunicationError("CONTRACT_INVALID", "A missing distribution value cannot be explicitly excluded.")
            missing += 1
            continue
        parsed = decimal_value(raw, field=f"values[{index}]")
        if index in exclusion_map:
            excluded.append({"index": index, "value": _decimal_text(parsed), "reason": exclusion_map[index]})
        else:
            included.append(parsed)
            counts[parsed] += 1
    included.sort()
    result: dict[str, Any] = {
        "unit": unit.strip(), "count_total": len(values), "count": len(included),
        "missing_count": missing, "excluded_count": len(excluded), "excluded": excluded,
        "exclusion_method": "explicit_user_rule" if excluded else None,
        "epistemic": ("DERIVED_VALUE" if epistemic in {"MEASUREMENT", "OBSERVATION", "FACT", "DERIVED_VALUE"} else epistemic) if included else "UNKNOWN",
    }
    if not included:
        result["statistics"] = None
        result["outliers"] = []
        return result
    with localcontext() as context:
        context.prec = 28
        mean = sum(included, Decimal(0)) / Decimal(len(included))
        variance = sum(((item - mean) ** 2 for item in included), Decimal(0)) / Decimal(len(included))
        stddev = variance.sqrt()
    q1 = _quantile(included, Decimal("0.25"))
    q3 = _quantile(included, Decimal("0.75"))
    iqr = q3 - q1
    low_fence = q1 - Decimal("1.5") * iqr
    high_fence = q3 + Decimal("1.5") * iqr
    result["statistics"] = {
        "mean": _decimal_text(mean), "median": _decimal_text(_quantile(included, Decimal("0.5"))),
        "p50": _decimal_text(_quantile(included, Decimal("0.5"))),
        "p90": _decimal_text(_quantile(included, Decimal("0.9"))),
        "p95": _decimal_text(_quantile(included, Decimal("0.95"))),
        "p99": _decimal_text(_quantile(included, Decimal("0.99"))),
        "variance": _decimal_text(variance), "standard_deviation": _decimal_text(stddev),
        "min": _decimal_text(included[0]), "max": _decimal_text(included[-1]),
        "q1": _decimal_text(q1), "q3": _decimal_text(q3),
    }
    result["outlier_method"] = "1.5_iqr_fence"
    result["outliers"] = [{"value": _decimal_text(item), "count": counts[item]}
                          for item in sorted(counts) if item < low_fence or item > high_fence]
    result["outlier_values_retained"] = True
    return result


def analyze_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CommunicationError("CONTRACT_INVALID", "Quantitative input must be a JSON object.")
    metrics = raw.get("metrics", [])
    if not isinstance(metrics, list) or len(metrics) > 500:
        raise CommunicationError("CONTRACT_INVALID", "Quantitative metrics must be a bounded list.")
    insights = [analyze_metric(metric) for metric in metrics]
    metric_ids = [item["id"] for item in insights]
    if len(metric_ids) != len(set(metric_ids)):
        raise CommunicationError("CONTRACT_INVALID", "Quantitative metric IDs must be unique.")
    distributions = []
    distribution_ids: set[str] = set()
    raw_distributions = raw.get("distributions", [])
    if not isinstance(raw_distributions, list) or len(raw_distributions) > 500:
        raise CommunicationError("CONTRACT_INVALID", "Distributions must be a bounded list.")
    for item in raw_distributions:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not IDENTIFIER.fullmatch(item["id"]):
            raise CommunicationError("CONTRACT_INVALID", "Each distribution needs an ID.")
        if item["id"] in distribution_ids:
            raise CommunicationError("CONTRACT_INVALID", "Distribution IDs must be unique.")
        distribution_ids.add(item["id"])
        label = item.get("metric", item["id"])
        if not isinstance(label, str) or not label.strip() or len(label) > 240:
            raise CommunicationError("CONTRACT_INVALID", f"Distribution {item['id']} metric label must be short text.")
        summary = distribution_summary(item.get("values"), unit=item.get("unit", ""), exclusions=item.get("exclusions"),
                                       epistemic=item.get("epistemic", "MEASUREMENT"))
        distributions.append({"id": item["id"], "metric": label.strip(), **summary})
    return {"schema_version": 1, "quantitative_insights": insights, "distributions": distributions}


def rank_insights(insights: list[dict[str, Any]], question: str) -> list[dict[str, Any]]:
    """Rank measures according to the explicit comparison question."""
    if question not in {"absolute_impact", "relative_improvement"}:
        raise CommunicationError("CONTRACT_INVALID", "Ranking question must be absolute_impact or relative_improvement.")
    if question == "absolute_impact":
        units = {item.get("unit") for item in insights if item.get("absolute_change") is not None}
        if len(units) > 1:
            raise CommunicationError("UNIT_MISMATCH", "Absolute impact ranking requires comparable units; convert values explicitly before ranking.")

    def score(item: dict[str, Any]) -> Decimal | None:
        if question == "absolute_impact":
            value = item.get("absolute_change")
        else:
            value = item.get("relative_change") if item.get("interpretation") == "favorable" else None
        return abs(decimal_value(value, field="ranking score")) if value is not None else None
    ranked = sorted(insights, key=lambda item: (score(item) is None, -(score(item) or Decimal(0)), str(item.get("id", ""))))
    return [{"id": item.get("id"), "score": _decimal_text(score(item)), "question": question,
             "rationale": "Ranked by absolute change magnitude." if question == "absolute_impact"
             else "Ranked by favorable relative improvement; unfavorable, unknown, and undefined comparisons remain unranked."} for item in ranked]


def format_number(value: Any, *, locale: str = "en", decimals: int = 2) -> str:
    parsed = decimal_value(value, field="number")
    if decimals < 0 or decimals > 8:
        raise CommunicationError("CONTRACT_INVALID", "Presentation precision must be between zero and eight decimals.")
    quantum = Decimal(1).scaleb(-decimals)
    with localcontext() as context:
        context.prec = max(28, len(parsed.as_tuple().digits) + abs(parsed.as_tuple().exponent) + decimals + 3)
        rounded = parsed.quantize(quantum, rounding=ROUND_HALF_UP)
    text = f"{rounded:,.{decimals}f}"
    if locale.casefold() in {"pt", "pt-br", "pt_br"}:
        text = text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return text


def _communicative_number(value: Any, *, locale: str) -> str:
    """Compact an executive display while leaving the exact value in the plan/evidence."""
    parsed = decimal_value(value, field="presentation number")
    magnitude = abs(parsed)
    if magnitude >= Decimal("1000000000"):
        scale, suffix = Decimal("1000000000"), "B"
    elif magnitude >= Decimal("1000000"):
        scale, suffix = Decimal("1000000"), "M"
    elif magnitude >= Decimal("1000"):
        scale, suffix = Decimal("1000"), "k"
    else:
        if parsed == parsed.to_integral_value():
            return format_number(parsed, locale=locale, decimals=0)
        return format_number(parsed, locale=locale, decimals=1)
    rounded = parsed / scale
    rendered = format_number(rounded, locale=locale, decimals=1)
    decimal_marker = "," if locale.casefold() in {"pt", "pt-br", "pt_br"} else "."
    if rendered.endswith(decimal_marker + "0"):
        rendered = rendered[:-2]
    return "~" + rendered + suffix


def format_metric(insight: dict[str, Any], *, audience: str, locale: str = "en") -> str:
    """Render a concise audience-aware statement without changing analytical values."""
    audiences = {"executive", "financial", "technical_leadership", "engineering", "technical", "mixed"}
    if audience not in audiences:
        raise CommunicationError("CONTRACT_INVALID", "Audience must be executive, financial, technical_leadership, engineering, technical, or mixed.")
    unit = insight["unit"]
    delta = insight.get("absolute_change")
    is_pt = locale.casefold() in {"pt", "pt-br", "pt_br"}
    if delta is None:
        message = "comparação indisponível" if is_pt else "comparison unavailable"
        return f"{insight['metric']}: {message} ({'unidade' if is_pt else 'unit'}: {unit})."
    parsed = decimal_value(delta, field="absolute_change")
    compact_audiences = {"executive", "financial"}
    detailed_audiences = {"technical", "technical_leadership", "engineering", "mixed"}
    decimals = 0 if insight.get("kind") == "count" or unit in {"count", "execution"} else 2
    magnitude = (_communicative_number(abs(parsed), locale=locale)
                 if audience in compact_audiences and insight.get("kind") == "amount"
                 else format_number(abs(parsed), locale=locale, decimals=decimals))
    relative = insight.get("relative_change")
    relative_text = (f" ({format_number(relative, locale=locale, decimals=1)}% {'relativo' if is_pt else 'relative'})"
                     if relative is not None else "")
    pp = insight.get("percentage_point_change")
    if parsed < 0:
        direction = "diminuiu" if is_pt else "decreased"
    elif parsed > 0:
        direction = "aumentou" if is_pt else "increased"
    else:
        direction = "permaneceu estável" if is_pt else "was unchanged"
    if pp is not None:
        pp_magnitude = format_number(abs(decimal_value(pp, field="percentage_point_change")), locale=locale, decimals=1)
        change_text = f"{direction} {pp_magnitude} pontos percentuais" if is_pt else f"{direction} by {pp_magnitude} percentage points"
    else:
        change_text = f"{direction} {magnitude} {unit}" if is_pt else f"{direction} by {magnitude} {unit}"
    if audience == "financial" and insight.get("kind") == "amount":
        baseline = insight.get("baseline") or {}
        current = insight.get("current") or {}
        baseline_value, current_value = baseline.get("value"), current.get("value")
        if baseline_value is not None and current_value is not None:
            period = ""
            if baseline.get("period") or current.get("period"):
                period = f" ({baseline.get('period') or 'unknown period'} → {current.get('period') or 'unknown period'})"
            observed = (f"real observado: {_communicative_number(baseline_value, locale=locale)} → "
                        f"{_communicative_number(current_value, locale=locale)} {unit}{period}" if is_pt else
                        f"observed actual: {_communicative_number(baseline_value, locale=locale)} → "
                        f"{_communicative_number(current_value, locale=locale)} {unit}{period}")
            amount_change = (f"; {direction} {magnitude} {unit}{relative_text}" if is_pt else
                             f"; {direction} by {magnitude} {unit}{relative_text}")
            change_text = observed + amount_change
    projection = insight.get("projection")
    interpretation = insight.get("interpretation", "unknown")
    labels = {"favorable": "favorável" if is_pt else "favorable",
              "unfavorable": "desfavorável" if is_pt else "unfavorable",
              "neutral": "neutra" if is_pt else "neutral"}
    interpretation_text = (f"; {labels[interpretation]}" if interpretation in labels else
                           ("; interpretação de negócio desconhecida" if is_pt else "; business interpretation unknown"))
    epistemic = insight.get("epistemic", "UNKNOWN")
    epistemic_prefix = {
        "ESTIMATE": "Estimativa: " if is_pt else "Estimated: ",
        "ASSUMPTION": "Sob a hipótese: " if is_pt else "Under the assumption: ",
        "SCENARIO": "Cenário: " if is_pt else "Scenario: ",
        "INFERENCE": "Inferência: " if is_pt else "Inference: ",
        "UNKNOWN": "Valores de origem não verificados: " if is_pt else "Unverified source values: ",
        "PROPOSAL": "Proposta: " if is_pt else "Proposed: ",
        "PROJECTION": "Projeção: " if is_pt else "Projected: ",
    }.get(epistemic, "")
    confidence = insight.get("confidence", "UNKNOWN")
    confidence_text = ""
    if confidence in {"LOW", "UNKNOWN"}:
        confidence_text = ("; confiança baixa" if confidence == "LOW" else "; confiança não avaliada") if is_pt else (
            "; low confidence" if confidence == "LOW" else "; confidence not assessed")
    statement = f"{insight['metric']}: {epistemic_prefix}{change_text}{relative_text}{interpretation_text}{confidence_text}."
    if audience == "executive" and insight.get("kind") == "amount":
        baseline = insight.get("baseline")
        current = insight.get("current")
        baseline_value = baseline.get("value") if baseline else None
        current_value = current.get("value") if current else None
        if baseline_value is not None and current_value is not None:
            baseline_period = (baseline or {}).get("period")
            current_period = (current or {}).get("period")
            statement += (f" Baseline → current: {_communicative_number(baseline_value, locale=locale)} {unit}"
                          f" → {_communicative_number(current_value, locale=locale)} {unit}"
                          f"{f' ({baseline_period} → {current_period})' if baseline_period or current_period else ''}.")
    if audience in detailed_audiences:
        baseline = insight.get("baseline")
        current = insight.get("current")
        baseline_value = baseline.get("value") if baseline else None
        current_value = current.get("value") if current else None
        if audience == "technical_leadership":
            if is_pt:
                statement += (f" Base → atual: {baseline_value if baseline_value is not None else 'desconhecida'}"
                              f" → {current_value if current_value is not None else 'desconhecido'} {unit}.")
            else:
                statement += (f" Baseline → current: {baseline_value if baseline_value is not None else 'unknown'}"
                              f" → {current_value if current_value is not None else 'unknown'} {unit}.")
            if (baseline or {}).get("period") or (current or {}).get("period"):
                statement += (f" Period: {(baseline or {}).get('period') or 'unknown'} → {(current or {}).get('period') or 'unknown'}."
                              if not is_pt else
                              f" Período: {(baseline or {}).get('period') or 'desconhecido'} → {(current or {}).get('period') or 'desconhecido'}.")
        elif is_pt:
            statement += (f" Base {baseline_value if baseline_value is not None else 'desconhecida'} {unit}"
                          f" ({(baseline or {}).get('period') or 'período desconhecido'});"
                          f" atual {current_value if current_value is not None else 'desconhecido'} {unit}"
                          f" ({(current or {}).get('period') or 'período desconhecido'}).")
        else:
            statement += (f" Baseline {baseline_value if baseline_value is not None else 'unknown'} {unit}"
                          f" ({(baseline or {}).get('period') or 'period unknown'});"
                          f" current {current_value if current_value is not None else 'unknown'} {unit}"
                          f" ({(current or {}).get('period') or 'period unknown'}).")
        normalization = insight.get("normalization")
        if normalization and normalization.get("baseline") is not None and normalization.get("current") is not None:
            base_normalized = format_number(normalization["baseline"], locale=locale, decimals=2)
            current_normalized = format_number(normalization["current"], locale=locale, decimals=2)
            normalized_relative = normalization.get("relative_change")
            normalized_relative_text = (f" ({format_number(normalized_relative, locale=locale, decimals=1)}% {'relativo' if is_pt else 'relative'})"
                                        if normalized_relative is not None else "")
            lead = "Normalizado" if is_pt else "Normalized"
            statement += (f" {lead} {normalization['name']}: {base_normalized} → {current_normalized}"
                          f" {normalization['unit']}{normalized_relative_text}.")
    if projection:
        projection_value = decimal_value(projection["value"], field="projection.value")
        prefix = "Projeção anualizada" if is_pt else "Annualized projection"
        projection_sign = "−" if projection_value < 0 else "+" if projection_value > 0 else ""
        statement += (f" {prefix}: {projection_sign}{format_number(abs(projection_value), locale=locale, decimals=2)} {unit};"
                      f" {projection['assumption']}")
    return statement


def verify_insight(insight: Any) -> dict[str, Any]:
    """Recompute an insight from its observations and reject hand-edited derived values."""
    if not isinstance(insight, dict):
        raise CommunicationError("CONTRACT_INVALID", "Quantitative insight must be an object.")
    metric: dict[str, Any] = {
        "id": insight.get("id"), "name": insight.get("metric"), "kind": insight.get("kind"),
        "unit": insight.get("unit"), "semantics": insight.get("semantics"),
        "baseline": insight.get("baseline"), "current": insight.get("current"),
        "confidence": insight.get("confidence", "UNKNOWN"),
        "baseline_semantics": insight.get("baseline_semantics"),
    }
    projection = insight.get("projection")
    if projection is not None:
        if not isinstance(projection, dict):
            raise CommunicationError("QUANTITATIVE_ANALYSIS_INVALID", f"Insight {insight.get('id')} projection must be an object.")
        metric["annualize"] = {"period_days": projection.get("basis_period_days"),
                                "assumption": projection.get("assumption")}
    normalized = insight.get("normalization")
    if normalized is not None:
        if not isinstance(normalized, dict):
            raise CommunicationError("QUANTITATIVE_ANALYSIS_INVALID", f"Insight {insight.get('id')} normalization must be an object.")
        metric["normalization"] = {
            "name": normalized.get("name"), "unit": normalized.get("unit"),
            "denominator_unit": normalized.get("denominator_unit"),
            "baseline_denominator": normalized.get("baseline_denominator"),
            "current_denominator": normalized.get("current_denominator"),
            "baseline_denominator_evidence_ids": normalized.get("baseline_denominator_evidence_ids", []),
            "current_denominator_evidence_ids": normalized.get("current_denominator_evidence_ids", []),
        }
    expected = analyze_metric(metric)
    fields = ("id", "metric", "kind", "unit", "semantics", "baseline", "current",
              "absolute_change", "relative_change", "percentage_point_change", "direction",
              "interpretation", "epistemic", "confidence", "baseline_semantics", "warnings",
              "projection", "normalization")
    for field in fields:
        actual = insight.get(field)
        wanted = expected.get(field)
        if actual != wanted:
            raise CommunicationError("QUANTITATIVE_ANALYSIS_INVALID",
                                     f"Insight {insight.get('id')} field {field} does not match its source observations.")
    return expected
