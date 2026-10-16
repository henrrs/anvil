#!/usr/bin/env python3
"""Deterministic evidence scoring and conservative Databricks FinOps triage."""

from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any


def number(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def confidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Return an evidence quality score, never a probability of success."""
    sample_runs = int(number(evidence.get("run_count"), 0) or 0)
    if sample_runs >= 20:
        sample = 20
    elif sample_runs >= 10:
        sample = 14
    elif sample_runs >= 5:
        sample = 8
    else:
        sample = 4

    coverage = max(0.0, min(1.0, number(evidence.get("telemetry_coverage"), 0.0) or 0.0))
    telemetry = round(20 * coverage)
    age = number(evidence.get("freshness_hours"))
    if age is None:
        freshness = 0
    elif age <= 24:
        freshness = 15
    elif age <= 24 * 7:
        freshness = 11
    elif age <= 24 * 30:
        freshness = 6
    else:
        freshness = 0

    attribution_kind = str(evidence.get("cost_attribution") or "unknown").casefold()
    attribution = {"dedicated": 15, "serverless": 15, "warehouse": 15, "shared": 4}.get(attribution_kind, 8)
    independent = evidence.get("independent_signals", [])
    signals = min(15, len(set(independent)) * 4) if isinstance(independent, list) else 0
    config_history = str(evidence.get("configuration_history") or "missing").casefold()
    configuration = {"complete": 15, "partial": 8}.get(config_history, 0)
    components = {
        "sample_sufficiency": sample,
        "telemetry_coverage": telemetry,
        "freshness": freshness,
        "cost_attribution_quality": attribution,
        "independent_signal_agreement": signals,
        "configuration_history": configuration,
    }
    penalties: dict[str, int] = {}
    if evidence.get("system_tables_access") is False:
        penalties["system_tables_unavailable"] = 30
    if sample_runs < 3:
        penalties["very_few_runs"] = 8
    if coverage < 0.5:
        penalties["incomplete_telemetry"] = 10
    if evidence.get("short_lived_compute") is True:
        penalties["short_lived_compute_underrepresented"] = 10
    if evidence.get("billing_partial_or_stale") is True:
        penalties["billing_window_partial_or_stale"] = 10
    if evidence.get("signals_conflict") is True:
        penalties["conflicting_signals"] = 15
    score = max(0, min(100, sum(components.values()) - sum(penalties.values())))
    label = "HIGH" if score >= 80 else "MEDIUM" if score >= 55 else "LOW"
    return {"score": score, "label": label, "components": components, "penalties": penalties,
            "interpretation": "Evidence quality only; not a probability that an optimization will succeed."}


def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    workload_type = str(payload.get("workload_type") or "classic_compute").casefold()
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    score = confidence(evidence)
    limitations: list[str] = []
    candidates: list[dict[str, str]] = []

    if evidence.get("system_tables_access") is False:
        limitations.append("System-table access is unavailable; no utilization or cost conclusion is supported.")
        return result_contract(payload, score, limitations, candidates, sources, "insufficient_evidence")

    if workload_type in {"warehouse", "sql_warehouse"}:
        if any(key in metrics for key in ("cpu_avg_pct", "cpu_p95_pct", "memory_p95_pct", "worker_count_p95")):
            limitations.append("Classic node metrics were excluded from SQL warehouse conclusions.")
        warehouse_metrics = {key: metrics[key] for key in (
            "query_count", "queue_fraction", "query_p95_seconds", "idle_fraction", "scale_events",
            "running_hours", "size", "min_clusters", "max_clusters", "auto_stop_minutes",
        ) if key in metrics}
        warehouse_payload = dict(payload)
        warehouse_payload["metrics"] = warehouse_metrics
        warehouse_signals = [key for key in ("query_count", "queue_fraction", "query_p95_seconds", "idle_fraction", "scale_events") if metrics.get(key) is not None]
        if not warehouse_signals:
            limitations.append("No warehouse, query-history, or billing aggregates were supplied.")
        elif number(metrics.get("idle_fraction"), 0) is not None and (number(metrics.get("idle_fraction"), 0) or 0) >= 0.8 and (number(metrics.get("query_count"), 0) or 0) > 0:
            candidates.append({"class": "test_candidate", "finding": "High observed idle share; compare a smaller size or shorter auto-stop in a controlled window.", "evidence": "warehouse events, query history, and workload aggregates"})
        if evidence.get("cost_attribution") == "shared":
            limitations.append("Shared warehouse cost allocation is approximate; it is not measured per-query cost.")
        return result_contract(warehouse_payload, score, limitations, candidates, sources, "warehouse_analysis" if warehouse_signals else "insufficient_evidence")

    cpu_avg = number(metrics.get("cpu_avg_pct"))
    cpu_p95 = number(metrics.get("cpu_p95_pct"))
    cpu_max = number(metrics.get("cpu_max_pct"))
    memory_p95 = number(metrics.get("memory_p95_pct"))
    memory_max = number(metrics.get("memory_max_pct"))
    cpu_wait_p95 = number(metrics.get("cpu_wait_p95_pct"))
    observed_workers = number(metrics.get("worker_count_p95"))
    configured_max = number(metrics.get("max_workers"))
    coverage = number(evidence.get("telemetry_coverage"), 0) or 0
    runs = int(number(evidence.get("run_count"), 0) or 0)

    if coverage < 0.8:
        limitations.append("Telemetry coverage is below 80%; treat utilization summaries as incomplete.")
    if evidence.get("configuration_history") != "complete":
        limitations.append("Historical compute configuration coverage is incomplete.")
    if evidence.get("billing_partial_or_stale") is True:
        limitations.append("Billing data is partial or stale for the requested window.")
    if evidence.get("cost_attribution") == "shared":
        limitations.append("Shared all-purpose compute cost attribution is approximate, not a measured per-job cost.")

    peak_pressure = ((cpu_p95 is not None and cpu_p95 >= 80)
                     or (cpu_max is not None and cpu_max >= 95)
                     or (memory_p95 is not None and memory_p95 >= 80)
                     or (memory_max is not None and memory_max >= 95)
                     or (cpu_wait_p95 is not None and cpu_wait_p95 >= 30))
    low_average = cpu_avg is not None and cpu_avg < 35
    low_p95 = cpu_p95 is not None and cpu_p95 < 50 and memory_p95 is not None and memory_p95 < 60
    headroom_large = configured_max is not None and observed_workers is not None and configured_max >= max(2, observed_workers * 2)
    sample_and_coverage = runs >= 10 and coverage >= 0.8
    strong = (low_average and low_p95 and headroom_large and sample_and_coverage and not peak_pressure
              and (cpu_wait_p95 is None or cpu_wait_p95 < 10)
              and evidence.get("configuration_history") == "complete"
              and evidence.get("cost_attribution") not in {"shared", "unknown", None}
              and evidence.get("system_tables_access") is not False)

    if peak_pressure:
        finding = "no_aggressive_downsize"
        candidates.append({"class": "hold", "finding": "Observed peak CPU, memory, or CPU wait argues against an aggressive downsize.", "evidence": "p95/max telemetry and wait metrics"})
    elif strong:
        finding = "right_sizing_recommendation"
        candidates.append({"class": "recommendation", "finding": "Observed utilization and worker history support a conservative right-sizing review.", "evidence": "repeated runs, high telemetry coverage, low p95 CPU/memory, low wait, and historical configuration"})
    elif low_average or low_p95 or headroom_large:
        finding = "right_sizing_test_candidate"
        candidates.append({"class": "test_candidate", "finding": "Potential capacity headroom exists; validate a smaller configuration in a controlled run before production changes.", "evidence": "available utilization and worker-count aggregates"})
    else:
        finding = "no_supported_right_sizing_candidate"
        limitations.append("Available evidence does not support a right-sizing candidate.")
    if cpu_avg is not None and cpu_p95 is not None and cpu_avg < 35 <= cpu_p95:
        limitations.append("Low average CPU has higher p95 pressure; averages alone do not justify downsizing.")
    return result_contract(payload, score, limitations, candidates, sources, finding)


def result_contract(payload: dict[str, Any], score: dict[str, Any], limitations: list[str], candidates: list[dict[str, str]], sources: list[Any], finding: str) -> dict[str, Any]:
    scope = payload.get("scope") or payload.get("workload_type") or "unspecified workload"
    return {
        "scope": scope,
        "evidence_window": payload.get("evidence_window", "not specified"),
        "workload_identity": payload.get("workload_identity", "not specified"),
        "compute_configuration": payload.get("compute_configuration", "not available"),
        "observed_metrics": payload.get("metrics", {}),
        "observed_cost": payload.get("cost", "not available"),
        "cost_semantics": payload.get("cost_semantics", "Databricks usage/list-cost evidence only; not a full cloud bill"),
        "reliability_signals": payload.get("reliability_signals", "not available"),
        "sources_used": sources,
        "coverage_limitations": limitations,
        "optimization_candidates": candidates,
        "finding": finding,
        "evidence_confidence": score,
        "suggested_validation": payload.get("suggested_validation") or "Run a representative benchmark with the candidate settings and compare latency, reliability, and Databricks usage.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="-", help="JSON evidence file; stdin by default")
    args = parser.parse_args()
    try:
        text = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("input must be a JSON object")
        print(json.dumps(analyze(value), indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR invalid FinOps evidence: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
