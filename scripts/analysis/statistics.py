"""Shared deterministic calculations used by analytical and communication consumers."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any


def decimal_value(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def compare_values(baseline: Any, current: Any, *, near_zero: Decimal = Decimal("1e-12")) -> dict[str, str | None]:
    """Calculate an absolute delta and only a meaningful positive-baseline relative change."""
    before, after = decimal_value(baseline), decimal_value(current)
    delta = after - before if before is not None and after is not None else None
    relative = None
    if before is not None and delta is not None and before > near_zero:
        with localcontext() as context:
            context.prec = 28
            relative = delta / before * Decimal(100)
    return {"absolute_change": decimal_text(delta), "relative_change": decimal_text(relative),
            "unknown_reason": ("missing comparison value" if delta is None else
                               "relative change is undefined for a zero, near-zero, or negative baseline" if relative is None else None)}


def _quantile(values: list[Decimal], probability: Decimal) -> Decimal:
    if len(values) == 1:
        return values[0]
    position = Decimal(len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] * (Decimal(1) - fraction) + values[upper] * fraction


def quantile(values: list[Any], percentile: Any) -> Decimal | None:
    """Linear-interpolated percentile used by every deterministic Anvil consumer."""
    numbers = [decimal_value(value) for value in values]
    if any(value is None for value in numbers):
        raise ValueError("quantile values must be finite numbers")
    ordered = sorted(value for value in numbers if value is not None)
    if not ordered:
        return None
    probability = Decimal(str(percentile)) / Decimal(100)
    if probability < 0 or probability > 1:
        raise ValueError("percentile must be between zero and one hundred")
    return _quantile(ordered, probability)


def distribution_statistics(values: list[Any]) -> dict[str, Any] | None:
    """Return reproducible population summaries, preserving outlier values and counts."""
    numbers = [decimal_value(value) for value in values if value is not None]
    if any(value is None for value in numbers):
        raise ValueError("distribution values must be finite numeric values")
    ordered = sorted(value for value in numbers if value is not None)
    if not ordered:
        return None
    with localcontext() as context:
        context.prec = 28
        count = Decimal(len(ordered))
        mean = sum(ordered, Decimal(0)) / count
        variance = sum(((item - mean) ** 2 for item in ordered), Decimal(0)) / count
        stddev = variance.sqrt()
        q1, median, q3, p90, p95, p99 = (
            _quantile(ordered, Decimal("0.25")), _quantile(ordered, Decimal("0.5")),
            _quantile(ordered, Decimal("0.75")), _quantile(ordered, Decimal("0.90")),
            _quantile(ordered, Decimal("0.95")), _quantile(ordered, Decimal("0.99")),
        )
    iqr = q3 - q1
    low_fence, high_fence = q1 - Decimal("1.5") * iqr, q3 + Decimal("1.5") * iqr
    counts = Counter(ordered)
    outliers = [{"value": decimal_text(item), "count": count} for item, count in sorted(counts.items())
                if item < low_fence or item > high_fence]
    return {
        "count": len(ordered), "mean": decimal_text(mean), "median": decimal_text(median),
        "p50": decimal_text(median), "p90": decimal_text(p90), "p95": decimal_text(p95),
        "p99": decimal_text(p99), "variance": decimal_text(variance),
        "standard_deviation": decimal_text(stddev), "min": decimal_text(ordered[0]),
        "max": decimal_text(ordered[-1]), "q1": decimal_text(q1), "q3": decimal_text(q3),
        "iqr": decimal_text(iqr), "outlier_method": "1.5_iqr_fence", "outliers": outliers,
        "outlier_count": sum(item["count"] for item in outliers), "outlier_values_retained": True,
    }
