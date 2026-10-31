#!/usr/bin/env python3
"""Offline intent and analytical-intelligence contract, behavior, and budget tests."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "scripts"))
from analysis.adapter import artifact_components
from analysis.contracts import select_depth, validate_analysis_plan, validate_semantic_model, validate_task_brief
from analysis.errors import AnalysisError
from analysis.findings import rank_materiality, validate_result
from analysis.primitives import execute_plan
from analysis.profiling import profile_file
from communication.errors import CommunicationError
from communication.contracts import validate_artifact
from analyze import main as analyze_main


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def expect_code(code: str, function, *args, **kwargs) -> None:
    try:
        function(*args, **kwargs)
    except (AnalysisError, CommunicationError) as exc:
        check(exc.code == code, f"expected {code}, received {exc.code}: {exc}")
    else:
        raise AssertionError(f"expected error {code}")


def brief(request: str) -> dict:
    return {"schema_version": 1, "original_request": request, "objective": "Compare requested measures and explain material changes.",
            "audience": "unknown", "expected_outcome": "An evidence-grounded answer.",
            "explicit_requirements": [{"text": "Compare the selected periods."}],
            "derived_requirements": [{"text": "Check population comparability.", "rationale": "Population movement can alter period comparisons."}],
            "constraints": [], "quality_attributes": ["traceable"], "evidence_expectations": ["Source hash and periods"],
            "ambiguities": [], "non_goals": ["Do not infer causation."], "success_criteria": ["Every conclusion cites evidence."]}


def finding(identifier: str, evidence_id: str, dimensions: dict, kind: str = "DERIVED") -> dict:
    return {"id": identifier, "question": "What changed?", "statement": f"Finding {identifier}.", "type": kind,
            "evidence_ids": [evidence_id], "confidence": "HIGH",
            "materiality": {"overall": "MEDIUM", "dimensions": dimensions, "rationale": "Compared named decision and population dimensions."},
            "periods": ["2026-01", "2026-03"], "segment": "", "magnitude": "measured", "unit": "count",
            "caveats": [], "alternatives": []}


def run() -> None:
    started = time.perf_counter()
    data = ROOT / "tests/fixtures/analysis/monthly-operations.csv"
    profile = profile_file(data)
    check(profile["row_count"] == 6 and profile["profiled_rows"] == 6 and profile["statistics_scope"] == "complete",
          "complete table profile reports exact rows and complete scope")
    by_name = {item["name"]: item for item in profile["columns"]}
    check(by_name["period"]["inferred_type"] == "temporal", "ISO month values are recognized as temporal")
    check(by_name["volume"]["numeric"]["sum"] == "118" and "measure" in by_name["volume"]["candidate_roles"],
          "profile reports deterministic measure summaries and roles as candidates")
    check("candidate_rate" in by_name["success_percent"]["candidate_roles"],
          "generic lexical profile hints suggest rates without asserting business semantics")
    check(by_name["owner"]["distinct_count"] == 3 and by_name["owner"]["null_count"] == 1,
          "categorical distinct count and missing coverage are deterministic")
    check(select_depth(profile, importance="LOW") == "FAST" and select_depth(profile, importance="HIGH") == "DEEP",
          "automatic depth stays cheap for a small, low-importance task and expands for high decision importance")

    original = "Compare volume and performance, including population change."
    compiled = validate_task_brief(brief(original), original_request=original)
    check(compiled["original_request"] == original and len(compiled["derived_requirements"]) == 1,
          "intent contract preserves the exact original request and separates derived requirements")
    whitespace_request = "  Summarize this table.\n"
    check(validate_task_brief(brief(whitespace_request), original_request=whitespace_request)["original_request"] == whitespace_request,
          "original request whitespace is retained byte-for-byte")
    changed = brief(original + " and recommend a budget.")
    expect_code("INTENT_PROVENANCE_INVALID", validate_task_brief, changed, original_request=original)
    invalid = brief(original)
    invalid["derived_requirements"][0].pop("rationale")
    expect_code("CONTRACT_INVALID", validate_task_brief, invalid)
    expect_code("SEMANTIC_REFERENCE_INVALID", validate_semantic_model,
                {"schema_version": 1, "columns": [{"name": "missing", "role": "measure", "confidence": "LOW", "interpretation": "Possible measure"}]},
                known_columns=set(by_name))
    uncertain_semantics = validate_semantic_model({"schema_version": 1, "columns": [
        {"name": "owner", "role": "unknown", "confidence": "LOW", "interpretation": "Could be a team or an individual.",
         "rationale": "The values alone do not establish an organizational meaning."}],
        "open_questions": ["What does owner represent in this source?"]}, known_columns=set(by_name))
    check(uncertain_semantics["columns"][0]["role"] == "unknown"
          and uncertain_semantics["columns"][0]["confidence"] == "LOW",
          "ambiguous column meanings remain explicitly low-confidence instead of becoming semantic facts")

    plan = {"schema_version": 1, "source_sha256": profile["source"]["sha256"], "depth": "DEEP",
            "primary_question": "Does the volume/performance change persist after comparing the same entities?",
            "questions": ["How did volume change?", "How did average latency change?", "Did the population change?"],
            "operations": [
                {"id": "row-count", "operation": "count"},
                {"id": "volume-sum", "operation": "sum", "column": "volume"},
                {"id": "latency-mean", "operation": "mean", "column": "latency_minutes"},
                {"id": "latency-median", "operation": "median", "column": "latency_minutes"},
                {"id": "latency-p95", "operation": "percentile", "column": "latency_minutes", "percentile": 95},
                {"id": "owners", "operation": "distinct_count", "column": "owner"},
                {"id": "min-volume", "operation": "min", "column": "volume"},
                {"id": "max-volume", "operation": "max", "column": "volume"},
                {"id": "volume-per-eligible", "operation": "ratio", "numerator": "volume", "denominator": "eligible",
                 "numerator_unit": "items", "denominator_unit": "entities", "result_unit": "items/entities"},
                {"id": "evaluation-coverage", "operation": "coverage", "column": "evaluated", "denominator": "eligible"},
                {"id": "latency-distribution", "operation": "distribution", "column": "latency_minutes"},
                {"id": "volume-change", "operation": "delta", "column": "volume", "period_column": "period", "baseline": "2026-01-01", "current": "2026-03-01"},
                {"id": "volume-relative-change", "operation": "delta_percent", "column": "volume", "period_column": "period", "baseline": "2026-01-01", "current": "2026-03-01"},
                {"id": "success-point-change", "operation": "delta_percentage_points", "column": "success_percent", "unit": "percent", "period_column": "period", "baseline": "2026-01-01", "current": "2026-03-01", "aggregate": "mean"},
                {"id": "latency-trend", "operation": "trend", "column": "latency_minutes", "period_column": "period", "aggregate": "mean"},
                {"id": "entity-cohort", "operation": "cohort", "column": "latency_minutes", "period_column": "period", "baseline": "2026-01-01", "current": "2026-03-01", "entity_column": "entity", "aggregate": "mean"},
                {"id": "volume-latency-correlation", "operation": "correlation", "x_column": "volume", "y_column": "latency_minutes"},
                {"id": "latency-volatility", "operation": "volatility", "column": "latency_minutes"},
                {"id": "top-owner-volume", "operation": "top_n", "column": "volume", "group_by": ["owner"], "limit": 2},
                {"id": "volume-concentration", "operation": "concentration", "column": "volume", "group_by": ["owner"], "limit": 1},
            ],
            "stop_conditions": ["Stop when the primary comparison and cohort are calculated."],
            "budgets": {"max_rows": 100, "max_groups": 20}}
    validated_plan = validate_analysis_plan(plan)
    result = execute_plan(str(data), validated_plan)
    operations = {item["id"]: item["results"] for item in result["operations"]}
    check(result["profile"]["complete"] and operations["row-count"][0]["value"] == "6",
          "deterministic execution is complete and counts rows")
    check(operations["volume-change"][0]["delta"] == "18" and operations["volume-relative-change"][0]["relative_change"] == "60",
          "period volume and percent change are computed from source rows")
    check(operations["success-point-change"][0]["delta"] == "1" and operations["success-point-change"][0]["delta_unit"] == "percentage_points",
          "percentage-point movement remains distinct")
    check(operations["entity-cohort"][0]["common_entities"] == 1 and operations["entity-cohort"][0]["added_entities"] == 1
          and operations["entity-cohort"][0]["removed_entities"] == 1
          and operations["entity-cohort"][0]["like_for_like_delta"] == "-20",
          "common/added/removed population and like-for-like change are calculated separately")
    check(operations["latency-mean"][0]["value"] == "180" and operations["latency-distribution"][0]["statistics"]["median"] == "150",
          "mean and distribution reveal different aggregate views")
    check(operations["latency-trend"][0]["trend_supported"] is True,
          "three observed periods permit cautious trend analysis")
    check("does not establish causation" in operations["volume-latency-correlation"][0]["interpretation"],
          "correlation output explicitly rejects causal interpretation")
    check(operations["evaluation-coverage"][0]["coverage_ratio"] == "0.8333333333333333333333333333",
          "coverage compares the observed population with its explicit eligible denominator")
    fast_over = {**plan, "depth": "FAST", "operations": plan["operations"][:5], "questions": []}
    expect_code("ANALYSIS_BUDGET_EXCEEDED", validate_analysis_plan, fast_over)
    expect_code("EVIDENCE_PROVENANCE_INVALID", validate_analysis_plan, {**plan, "source_sha256": "stale"})
    wrong_source = {**plan, "source_sha256": "0" * 64}
    expect_code("INPUT_SOURCE_CHANGED", execute_plan, str(data), wrong_source)
    wrong_column = {**plan, "operations": [{"id": "unknown-column", "operation": "sum", "column": "not_a_field"}]}
    expect_code("PLAN_COLUMN_UNKNOWN", execute_plan, str(data), wrong_column)

    with tempfile.TemporaryDirectory(prefix="anvil-analysis-") as temporary:
        root = Path(temporary)
        two_period = root / "two-period.csv"
        two_period.write_text("period,value\n2026-01,10\n2026-02,12\n", encoding="utf-8")
        two_profile = profile_file(two_period)
        two_point = execute_plan(str(two_period), {"schema_version": 1, "source_sha256": two_profile["source"]["sha256"],
            "depth": "FAST", "primary_question": "What changed?", "questions": ["How did the value change?"],
            "operations": [{"id": "two-point", "operation": "trend", "column": "value", "period_column": "period"}],
            "budgets": {"max_rows": 100, "max_groups": 10}})
        check(len(two_point["operations"][0]["results"]) == 1
              and two_point["operations"][0]["results"][0]["trend_supported"] is False,
              "two observations are explicitly not classified as a trend")
        check(two_point["operations"][0]["results"][0]["endpoint_change"] == "2",
              "two temporal observations still expose a comparison change")
        short = root / "short.csv"
        short.write_text("a,b\n1,x\n2,y\n3,z\n", encoding="utf-8")
        sampled = profile_file(short, max_rows=2)
        check(sampled["row_count"] == 3 and sampled["profiled_rows"] == 2 and sampled["statistics_scope"] == "sampled_prefix",
              "prefix-sampled profile retains exact total row count and explicit incompleteness")
        sample_plan = {"schema_version": 1, "source_sha256": sampled["source"]["sha256"], "depth": "FAST",
                       "primary_question": "How many rows?", "operations": [{"id": "n", "operation": "count"}],
                       "budgets": {"max_rows": 2}}
        expect_code("ANALYSIS_BUDGET_EXCEEDED", execute_plan, str(short), sample_plan)
        stale = root / "stale.csv"
        stale.write_text("value\n1\n", encoding="utf-8")
        stale_profile = profile_file(stale)
        stale_plan = {"schema_version": 1, "source_sha256": stale_profile["source"]["sha256"], "depth": "FAST",
                      "primary_question": "What changed?", "questions": [],
                      "operations": [{"id": "count", "operation": "count"}],
                      "budgets": {"max_rows": 10, "max_groups": 10}}
        stale.write_text("value\n2\n", encoding="utf-8")
        expect_code("INPUT_SOURCE_CHANGED", execute_plan, str(stale), stale_plan)
        json_file = root / "rows.json"
        json_file.write_text('[{"x":1,"group":"a"},{"x":2,"group":"b"}]', encoding="utf-8")
        trailing_json = root / "trailing-comma.json"
        trailing_json.write_text('[{"x":1},]', encoding="utf-8")
        duplicate_json = root / "duplicate-field.json"
        duplicate_json.write_text('[{"x":1,"x":2}]', encoding="utf-8")
        nested_jsonl = root / "nested-after-sample.jsonl"
        nested_jsonl.write_text('{"x":1}\n{"x":{"nested":true}}\n', encoding="utf-8")
        jsonl_file = root / "rows.jsonl"
        jsonl_file.write_text('{"x":1}\n{"x":2}\n', encoding="utf-8")
        tsv_file = root / "rows.tsv"
        tsv_file.write_text("x\tgroup\n1\ta\n2\tb\n", encoding="utf-8")
        na_file = root / "literal-na.csv"
        na_file.write_text("region\nNA\nn/a\n", encoding="utf-8")
        check(profile_file(json_file)["row_count"] == profile_file(jsonl_file)["row_count"] == profile_file(tsv_file)["row_count"] == 2,
              "JSON row arrays, JSON Lines, and TSV share the bounded profile interface")
        expect_code("INPUT_SCHEMA_INVALID", profile_file, trailing_json)
        expect_code("INPUT_SCHEMA_INVALID", profile_file, duplicate_json)
        expect_code("INPUT_SCHEMA_UNSUPPORTED", profile_file, nested_jsonl, max_rows=1)
        check(profile_file(na_file)["columns"][0]["null_count"] == 0,
              "ambiguous text values are not silently converted into missing data")
        with patch("analysis.profiling.MAX_SOURCE_BYTES", 4):
            expect_code("INPUT_LIMIT_EXCEEDED", profile_file, na_file)
        wide = root / "profile-cell-budget.csv"
        wide_header = ",".join(f"c{index}" for index in range(200))
        wide_row = ",".join("1" for _ in range(200))
        wide.write_text(wide_header + "\n" + (wide_row + "\n") * 1251, encoding="utf-8")
        expect_code("INPUT_LIMIT_EXCEEDED", profile_file, wide)
        link = root / "linked.csv"
        link.symlink_to(data)
        expect_code("INPUT_UNSAFE", profile_file, link)
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            check(analyze_main(["profile", str(short), "--max-rows", "2"]) == 0, "profile CLI returns success")
        check(json.loads(captured.getvalue())["profiled_rows"] == 2 and set(root.iterdir()) == {two_period, short, stale, json_file,
              trailing_json, duplicate_json, nested_jsonl, jsonl_file, tsv_file, na_file, wide, link},
              "local CLI emits JSON to stdout and creates no result/state files")

    levels = {key: "HIGH" for key in ("magnitude", "breadth", "persistence", "decision_relevance", "confidence", "exception_severity", "novelty")}
    medium = {key: "MEDIUM" for key in levels}
    incomparable_a = dict(levels, breadth="LOW", novelty="LOW", confidence="MEDIUM")
    incomparable_b = dict(levels, magnitude="LOW", exception_severity="LOW", confidence="HIGH")
    low = {key: "LOW" for key in levels}
    ev = [{"id": "E-data", "claim": "Calculated from the named source.", "epistemic": "DERIVED", "confidence": "HIGH",
           "source": {"type": "csv", "locator": str(data), "sha256": profile["source"]["sha256"]},
           "method": "sum(volume) by period", "data": operations["volume-change"]}]
    findings = [finding("F-a", "E-data", incomparable_a, "HYPOTHESIS"),
                finding("F-b", "E-data", incomparable_b), finding("F-c", "E-data", low)]
    tiers = rank_materiality(findings)
    check(tiers == [["F-a", "F-b"], ["F-c"]], "materiality uses explainable Pareto tiers without a weighted composite score")
    semantics = {"schema_version": 1, "columns": [
        {"name": "volume", "role": "measure", "confidence": "HIGH", "interpretation": "Observed numeric volume"},
        {"name": "period", "role": "temporal_dimension", "confidence": "HIGH", "interpretation": "Monthly period"}],
        "open_questions": []}
    analysis_result = {"schema_version": 1, "task_brief": brief("Analyze the operation data."), "profile": profile,
                       "semantic_model": semantics, "questions": ["How did volume change?"], "plan": plan,
                       "evidence": ev, "findings": findings[:1],
                       "narrative": {"main_conclusion": "The result is evidence linked and includes a hypothesis only as a hypothesis.",
                                     "what_changed": ["Volume rose in the selected periods."], "explanation": [],
                                     "unresolved": ["The hypothesis needs additional evidence."], "risks_opportunities": [],
                                     "next_actions": [], "finding_ids": ["F-a"]}, "limitations": ["Synthetic test data."]}
    checked = validate_result(analysis_result)
    components = artifact_components(analysis_result)
    check(components["evidence"][0]["data"] == operations["volume-change"]
          and components["findings"][0]["epistemic"] == "HYPOTHESIS"
          and checked["materiality_tiers"] == [["F-a"]],
          "artifact adapter preserves source, calculation result, hypothesis type and materiality ordering")
    artifact = {"schema_version": 1, "request": {"artifact": "summary", "audience": "technical", "purpose": "Test analytical adapter."},
                "title": "Analytical adapter", "thesis": "One grounded finding.", "evidence": components["evidence"],
                "findings": components["findings"], "quantitative_insights": [], "storyline": [], "sections": [
                    {"title": "Finding", "body": "The selected comparison is shown.", "finding_ids": ["F-a"],
                     "evidence_ids": ["E-data"], "insight_ids": []}]}
    validate_artifact(artifact)
    presentation = deepcopy(artifact)
    presentation["request"]["artifact"] = "presentation"
    presentation["sections"] = []
    presentation["slides"] = [{"role": "content", "title": "Volume rose across the selected periods.",
                               "body": "The measured change is linked to the same validated finding and evidence.",
                               "finding_ids": ["F-a"], "evidence_ids": ["E-data"], "insight_ids": []}]
    validate_artifact(presentation)
    bad_finding = deepcopy(analysis_result)
    bad_finding["findings"][0]["evidence_ids"] = ["missing"]
    expect_code("EVIDENCE_PROVENANCE_INVALID", validate_result, bad_finding)

    unrelated = ROOT / "tests/fixtures/analysis/helpdesk-tickets.csv"
    tickets = profile_file(unrelated)
    ticket_plan = {"schema_version": 1, "source_sha256": tickets["source"]["sha256"], "depth": "FAST",
                   "primary_question": "Which queues have the longest waits?", "questions": [],
                   "operations": [{"id": "wait-by-queue", "operation": "mean", "column": "wait_minutes", "group_by": ["queue"]}],
                   "budgets": {"max_rows": 100, "max_groups": 10}}
    grouped = execute_plan(str(unrelated), ticket_plan)["operations"][0]["results"]
    check({item["group"]["queue"] for item in grouped} == {"access", "billing"},
          "generic grouping transfers to an unrelated support dataset without domain-specific code")

    benchmark_data = ROOT / "tests/fixtures/analysis/operations-benchmark.csv"
    benchmark_profile = profile_file(benchmark_data)
    benchmark_plan = {"schema_version": 1, "source_sha256": benchmark_profile["source"]["sha256"],
        "depth": "STANDARD", "primary_question": "Did average latency improve without hiding population or segment changes?",
        "questions": ["How did latency change overall and by segment?", "Did the comparable population change?",
                      "Did volume and error distribution move?"],
        "operations": [
            {"id": "latency-by-period", "operation": "mean", "column": "latency_minutes", "group_by": ["period"]},
            {"id": "latency-by-period-segment", "operation": "mean", "column": "latency_minutes", "group_by": ["period", "segment"]},
            {"id": "latency-segment-trend", "operation": "trend", "column": "latency_minutes", "period_column": "period",
             "group_by": ["segment"], "aggregate": "mean"},
            {"id": "like-for-like", "operation": "cohort", "column": "latency_minutes", "period_column": "period",
             "baseline": "2026-01-01", "current": "2026-03-01", "entity_column": "entity", "aggregate": "mean"},
            {"id": "midpoint-population", "operation": "cohort", "column": "latency_minutes", "period_column": "period",
             "baseline": "2026-02-01", "current": "2026-03-01", "entity_column": "entity", "aggregate": "mean"},
            {"id": "volume-by-period", "operation": "sum", "column": "volume", "group_by": ["period"]},
            {"id": "error-distribution", "operation": "distribution", "column": "error_count", "group_by": ["period"]},
            {"id": "evaluation-coverage", "operation": "coverage", "column": "evaluated", "denominator": "eligible", "group_by": ["period"]},
            {"id": "stable-availability", "operation": "mean", "column": "availability_percent", "group_by": ["period"]}],
        "stop_conditions": ["Stop after period, segment, cohort, coverage and exception comparisons."],
        "budgets": {"max_rows": 100, "max_groups": 20}}
    benchmark_result = execute_plan(str(benchmark_data), benchmark_plan)
    benchmark_ops = {item["id"]: item["results"] for item in benchmark_result["operations"]}
    period_means = {item["group"]["period"]: item["value"] for item in benchmark_ops["latency-by-period"]}
    edge_means = [item for item in benchmark_ops["latency-by-period-segment"] if item["group"]["segment"] == "edge"]
    benchmark_cohort = benchmark_ops["like-for-like"][0]
    midpoint_cohort = benchmark_ops["midpoint-population"][0]
    benchmark_volumes = {item["group"]["period"]: item["value"] for item in benchmark_ops["volume-by-period"]}
    segment_trends = {item["group"]["segment"]: item for item in benchmark_ops["latency-segment-trend"]}
    march_errors = next(item for item in benchmark_ops["error-distribution"] if item["group"]["period"] == "2026-03-01")
    check(period_means == {"2026-01-01": "60", "2026-02-01": "52", "2026-03-01": "42.25"}
          and edge_means[0]["value"] == "105" and edge_means[-1]["value"] == "130",
          "benchmark exposes aggregate latency improvement alongside deteriorating edge-segment performance")
    check(benchmark_cohort["common_entities"] == 3 and benchmark_cohort["added_entities"] == 1
          and benchmark_cohort["removed_entities"] == 1 and benchmark_cohort["like_for_like_delta"] == "8.66666666666666666666666667",
          "benchmark distinguishes changing population from worsening common-cohort latency")
    check(benchmark_volumes == {"2026-01-01": "400", "2026-02-01": "500", "2026-03-01": "430"}
          and midpoint_cohort["eligible_baseline"] == 5 and midpoint_cohort["eligible_current"] == 4
          and midpoint_cohort["removed_entities"] == 1,
          "benchmark exercises both volume growth and subsequent population/volume contraction")
    check(segment_trends["core"]["trend_supported"] is True and segment_trends["edge"]["trend_supported"] is True
          and march_errors["statistics"]["outlier_count_1_5_iqr"] == 1
          and all(item["value"] == "99.9" for item in benchmark_ops["stable-availability"]),
          "three-period benchmark supports opposing segment trajectories, a material exception, and a stable metric")

    depth_benchmarks: dict[str, float] = {}
    with tempfile.TemporaryDirectory(prefix="anvil-analysis-benchmark-") as temporary:
        benchmark_source = Path(temporary) / "ten-thousand-rows.csv"
        with benchmark_source.open("w", encoding="utf-8", newline="") as stream:
            stream.write("segment,value\n")
            for index in range(10_000):
                stream.write(f"segment-{index % 10},{index % 97}\n")
        for depth, operation_count in (("FAST", 4), ("STANDARD", 12), ("DEEP", 20)):
            benchmark_started = time.perf_counter()
            benchmark_profile = profile_file(benchmark_source)
            benchmark_plan = {"schema_version": 1, "source_sha256": benchmark_profile["source"]["sha256"],
                "depth": depth, "primary_question": "How do the ten segments compare?", "questions": [],
                "operations": [{"id": f"sum-{index + 1}", "operation": "sum", "column": "value"}
                               for index in range(operation_count)],
                "budgets": {"max_rows": 10_000, "max_groups": 20}}
            benchmark_result = execute_plan(str(benchmark_source), benchmark_plan)
            depth_benchmarks[depth] = (time.perf_counter() - benchmark_started) * 1000
            check(benchmark_result["profile"]["analyzed_rows"] == 10_000
                  and len(benchmark_result["operations"]) == operation_count,
                  f"10k-row {depth} profile and bounded deterministic operations cover the input")

    elapsed = time.perf_counter() - started
    check(elapsed < 60, "bounded synthetic contracts and operations complete within 60 seconds")
    print(f"PASS intent provenance, adaptive budgets, profiling, primitives, cohorts, evidence, materiality and artifact separation ({elapsed * 1000:.1f} ms)")
    print("EVALUATION candidate 10k rows end-to-end profile+execution: "
          + ", ".join(f"{depth} ({count} operations) {depth_benchmarks[depth]:.1f} ms"
                       for depth, count in (("FAST", 4), ("STANDARD", 12), ("DEEP", 20)))
          + "; two source scans; helper model/tool calls: 0; helper prompt tokens: 0; baseline raw-table API: unavailable")


if __name__ == "__main__":
    run()
