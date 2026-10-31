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
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "scripts"))
from analysis.contracts import select_depth, validate_analysis_plan, validate_semantic_model, validate_task_brief
from analysis.errors import AnalysisError
from analysis.findings import rank_materiality, validate_result
from analysis.investigation import validate_claims
from analysis.primitives import execute_plan
from analysis.profiling import profile_file
from communication.errors import CommunicationError
from communication.contracts import validate_artifact
from communication.analysis_adapter import artifact_components
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
    result = execute_plan(str(data), validated_plan, profile=profile)
    operations = {item["id"]: item["results"] for item in result["operations"]}
    check(result["profile"]["complete"] and operations["row-count"][0]["value"] == "6",
          "deterministic execution is complete and counts rows")
    check(result["semantic_context"]["observations"]["count"] == 6
          and result["execution_metadata"]["semantic_profile_reused"] is True,
          "execution reuses the bounded semantic profile and keeps row count explicit")
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
        two_plan = {"schema_version": 1, "source_sha256": two_profile["source"]["sha256"],
            "depth": "FAST", "primary_question": "What changed?", "questions": ["How did the value change?"],
            "operations": [{"id": "two-point", "operation": "trend", "column": "value", "period_column": "period"}],
            "budgets": {"max_rows": 100, "max_groups": 10}}
        two_point = execute_plan(str(two_period), two_plan, profile=two_profile)
        check(len(two_point["operations"][0]["results"]) == 1
              and two_point["operations"][0]["results"][0]["trend_supported"] is False,
              "two observations are explicitly not classified as a trend")
        check(two_point["operations"][0]["results"][0]["endpoint_change"] == "2",
              "two temporal observations still expose a comparison change")
        two_trend_claim = validate_claims([{"id": "C-two-point", "statement": "This is a trend.", "classification": "DERIVED",
                                            "claim_type": "trend", "confidence": "HIGH", "evidence_ids": ["E-two"],
                                            "operation_id": "two-point"}], evidence_ids={"E-two"},
                                          plan=validate_analysis_plan(two_plan), execution=two_point)
        check(two_trend_claim[0]["validation"]["status"] == "REJECTED",
              "claim validation rejects trend language based on two periods")

        composite = root / "composite-grain.csv"
        with composite.open("w", encoding="utf-8", newline="") as stream:
            stream.write("entity_id,period,product_id,value\n")
            for entity_index in range(8):
                for period_index in range(10):
                    for product_index in range(2):
                        stream.write(f"entity-{entity_index},2026-{period_index + 1:02d},product-{product_index},{entity_index + period_index}\n")
        composite_profile = profile_file(composite)
        composite_context = composite_profile["semantic_context"]
        check(composite_context["observations"]["count"] == 160
              and composite_context["grain"]["confidence"] == "MEDIUM"
              and set(composite_context["grain"]["fields"]) == {"entity_id", "period", "product_id"}
              and {item["fields"][0] for item in composite_context["entities"]} >= {"entity_id", "product_id"},
              "semantic profiling distinguishes 160 observations, repeated entities and a composite entity-period-product grain")

        repeated = root / "repeated-cohort.csv"
        repeated.write_text(
            "entity_id,period,product_id,value\n"
            "entity-a,2026-01,product-1,0\n"
            "entity-b,2026-01,product-1,100\n"
            "entity-b,2026-01,product-2,100\n"
            "entity-d,2026-01,product-1,20\n"
            "entity-a,2026-02,product-1,10\n"
            "entity-a,2026-02,product-2,10\n"
            "entity-b,2026-02,product-1,90\n"
            "entity-c,2026-02,product-1,50\n"
            "entity-c,2026-02,product-2,50\n", encoding="utf-8")
        repeated_profile = profile_file(repeated)
        repeated_plan = {"schema_version": 1, "source_sha256": repeated_profile["source"]["sha256"],
                         "depth": "STANDARD", "primary_question": "Did the retained population change?",
                         "operations": [
                             {"id": "rows", "operation": "count"},
                             {"id": "unique-entities", "operation": "distinct_count", "column": "entity_id"},
                             {"id": "composite-keys", "operation": "distinct_count", "columns": ["entity_id", "period", "product_id"]},
                             {"id": "cohort", "operation": "cohort", "column": "value", "period_column": "period",
                              "baseline": "2026-01-01", "current": "2026-02-01", "entity_columns": ["entity_id"],
                              "aggregate": "mean", "improvement_direction": "increase"}],
                         "budgets": {"max_rows": 100, "max_groups": 20}}
        repeated_result = execute_plan(str(repeated), repeated_plan, profile=repeated_profile)
        repeated_ops = {item["id"]: item["results"] for item in repeated_result["operations"]}
        repeated_cohort = repeated_ops["cohort"][0]
        check(repeated_ops["rows"][0]["value"] == "9" and repeated_ops["unique-entities"][0]["value"] == "4"
              and repeated_ops["composite-keys"][0]["value"] == "9",
              "row, entity and composite-key cardinalities remain separate")
        check(repeated_cohort["common_entities"] == 2 and repeated_cohort["added_entities"] == 1
              and repeated_cohort["removed_entities"] == 1 and repeated_cohort["like_for_like_delta"] == "0"
              and repeated_cohort["improved_entities"] == 1 and repeated_cohort["improved_share"] == "0.5",
              "cohort aggregates repeated observations within each entity-period before like-for-like comparison")
        breadth_claims = validate_claims([
            {"id": "C-broad-75", "statement": "Change was broad-based.", "classification": "DERIVED",
             "claim_type": "broad_based_change", "confidence": "HIGH", "evidence_ids": ["E-cohort"],
             "operation_id": "cohort", "direction": "increase", "threshold": 0.75},
            {"id": "C-broad-50", "statement": "At least half of retained entities increased.", "classification": "DERIVED",
             "claim_type": "broad_based_change", "confidence": "HIGH", "evidence_ids": ["E-cohort"],
             "operation_id": "cohort", "direction": "increase", "threshold": 0.5},
        ], evidence_ids={"E-cohort"}, plan=validate_analysis_plan(repeated_plan), execution=repeated_result)
        check([item["validation"]["status"] for item in breadth_claims] == ["REJECTED", "VALIDATED"],
              "breadth conclusions are tested against the explicit retained-entity share threshold")

        stable_distribution = root / "stable-average-shifting-distribution.csv"
        stable_distribution.write_text("period,value,eligible,evaluated\n"
                                       "2026-01,0,10,8\n2026-01,10,10,8\n"
                                       "2026-02,5,10,6\n2026-02,5,10,6\n", encoding="utf-8")
        distribution_profile = profile_file(stable_distribution)
        distribution_plan = {"schema_version": 1, "source_sha256": distribution_profile["source"]["sha256"],
                             "depth": "STANDARD", "primary_question": "Did the distribution or coverage change?",
                             "operations": [
                                 {"id": "mean-by-period", "operation": "mean", "column": "value", "group_by": ["period"]},
                                 {"id": "period-change", "operation": "delta", "column": "value", "period_column": "period",
                                  "baseline": "2026-01-01", "current": "2026-02-01"},
                                 {"id": "distribution-by-period", "operation": "distribution", "column": "value", "group_by": ["period"]},
                                 {"id": "coverage-by-period", "operation": "coverage", "column": "evaluated", "denominator": "eligible", "group_by": ["period"]}],
                             "budgets": {"max_rows": 100, "max_groups": 10}}
        distribution_result = execute_plan(str(stable_distribution), distribution_plan, profile=distribution_profile)
        distribution_ops = {item["id"]: item["results"] for item in distribution_result["operations"]}
        means = {item["group"]["period"]: item["value"] for item in distribution_ops["mean-by-period"]}
        ranges = {item["group"]["period"]: str(Decimal(item["statistics"]["max"]) - Decimal(item["statistics"]["min"]))
                  for item in distribution_ops["distribution-by-period"]}
        coverages = {item["group"]["period"]: item["coverage_ratio"] for item in distribution_ops["coverage-by-period"]}
        check(means == {"2026-01-01": "5", "2026-02-01": "5"} and ranges == {"2026-01-01": "10", "2026-02-01": "0"},
              "a stable mean does not conceal material distribution movement")
        check(coverages == {"2026-01-01": "0.8", "2026-02-01": "0.6"},
              "coverage is calculated against its explicit changing denominator")
        coverage_claims = validate_claims([
            {"id": "C-period-change", "statement": "The measured value changed.", "classification": "DERIVED",
             "claim_type": "period_comparison", "confidence": "HIGH", "evidence_ids": ["E-period"], "operation_id": "period-change"},
            {"id": "C-coverage", "statement": "Coverage fell from 80% to 60%.", "classification": "DERIVED",
             "claim_type": "coverage", "confidence": "HIGH", "evidence_ids": ["E-period"], "operation_id": "coverage-by-period"},
        ], evidence_ids={"E-period"}, plan=validate_analysis_plan(distribution_plan), execution=distribution_result)
        check(coverage_claims[0]["validation"]["status"] == "QUALIFIED"
              and coverage_claims[0]["confidence"] == "LOW"
              and "Coverage changed" in coverage_claims[0]["limitations"][-1]
              and coverage_claims[1]["validation"]["status"] == "VALIDATED",
              "claim confidence is reduced when coverage shifts alongside a period comparison")

        broad_source = root / "broad-change.csv"
        broad_rows = [f"segment-{index},2026-01,10\nsegment-{index},2026-02,12\n" for index in range(4)]
        broad_source.write_text("segment,period,amount\n" + "".join(broad_rows), encoding="utf-8")
        concentrated_source = root / "concentrated-change.csv"
        concentrated_source.write_text("segment,period,amount\n"
                                       "segment-a,2026-01,80\nsegment-b,2026-01,10\nsegment-c,2026-01,10\n"
                                       "segment-a,2026-02,170\nsegment-b,2026-02,11\nsegment-c,2026-02,10\n", encoding="utf-8")
        contribution_results = []
        for source in (broad_source, concentrated_source):
            source_profile = profile_file(source)
            contribution_plan = {"schema_version": 1, "source_sha256": source_profile["source"]["sha256"],
                                 "depth": "FAST", "primary_question": "Which segments contributed to the movement?",
                                 "operations": [{"id": "contribution", "operation": "contribution", "column": "amount",
                                                 "period_column": "period", "baseline": "2026-01-01", "current": "2026-02-01",
                                                 "group_by": ["segment"], "aggregate": "sum", "unit": "items"}],
                                 "budgets": {"max_rows": 100, "max_groups": 10}}
            contribution = execute_plan(str(source), contribution_plan, profile=source_profile)
            contribution_results.append(contribution["operations"][0]["results"][0])
        broad_shares = [Decimal(item["share_of_absolute_change"]) for item in contribution_results[0]["groups"]]
        concentrated_shares = [Decimal(item["share_of_absolute_change"]) for item in contribution_results[1]["groups"]]
        check(all(share == Decimal("0.25") for share in broad_shares)
              and max(concentrated_shares) > Decimal("0.98"),
              "contribution distinguishes a broad shift from one segment explaining nearly all absolute movement")

        composition_source = root / "composition-shift.csv"
        composition_source.write_text("period,segment,metric\n"
                                      "2026-01,a,10\n2026-01,a,10\n2026-01,a,10\n2026-01,b,20\n"
                                      "2026-02,a,10\n2026-02,b,20\n2026-02,b,20\n2026-02,b,20\n", encoding="utf-8")
        composition_profile = profile_file(composition_source)
        composition_plan = {"schema_version": 1, "source_sha256": composition_profile["source"]["sha256"],
                            "depth": "FAST", "primary_question": "Did the category mix shift?",
                            "operations": [{"id": "mix", "operation": "composition", "column": "metric",
                                            "period_column": "period", "baseline": "2026-01-01", "current": "2026-02-01",
                                            "group_by": ["segment"], "aggregate": "mean", "unit": "points"}],
                            "budgets": {"max_rows": 20, "max_groups": 10}}
        composition_execution = execute_plan(str(composition_source), composition_plan, profile=composition_profile)
        composition = composition_execution["operations"][0]["results"][0]
        composition_groups = {item["group"]["segment"]: item for item in composition["groups"]}
        check(composition["composition_shift"] == "0.5" and composition["overall_metric_delta"] == "5"
              and composition_groups["a"]["share_delta"] == "-0.5"
              and composition_groups["b"]["share_delta"] == "0.5"
              and composition_groups["a"]["metric_delta"] == "0"
              and composition_groups["b"]["metric_delta"] == "0",
              "composition exposes changing category shares alongside stable segment metrics without claiming causality")
        composition_claims = validate_claims([
            {"id": "C-mix-shift", "statement": "Category mix changed materially.", "classification": "DERIVED",
             "claim_type": "composition", "confidence": "HIGH", "evidence_ids": ["E-mix"],
             "operation_id": "mix", "threshold": 0.25},
            {"id": "C-mix-overstated", "statement": "Category mix shifted by at least 75%.", "classification": "DERIVED",
             "claim_type": "composition", "confidence": "HIGH", "evidence_ids": ["E-mix"],
             "operation_id": "mix", "threshold": 0.75}], evidence_ids={"E-mix"},
            plan=validate_analysis_plan(composition_plan), execution=composition_execution)
        check([item["validation"]["status"] for item in composition_claims] == ["VALIDATED", "REJECTED"]
              and composition_claims[1]["confidence"] == "LOW",
              "composition claim checks respect measured category-share movement and lower rejected confidence")

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
              trailing_json, duplicate_json, nested_jsonl, jsonl_file, tsv_file, na_file, wide, link, composite, repeated,
              stable_distribution, broad_source, concentrated_source, composition_source},
              "local CLI emits JSON to stdout and creates no result/state files")
        profile_contract = root / "profile.json"
        plan_contract = root / "plan.json"
        profile_contract.write_text(json.dumps(profile), encoding="utf-8")
        plan_contract.write_text(json.dumps(validated_plan), encoding="utf-8")
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            check(analyze_main(["execute", str(data), str(plan_contract), "--profile", str(profile_contract)]) == 0,
                  "execution CLI accepts the optional reusable profile")
        cli_execution = json.loads(captured.getvalue())
        check(cli_execution["execution_metadata"]["semantic_profile_reused"] is True
              and cli_execution["semantic_context"]["observations"]["count"] == profile["row_count"],
              "CLI profile reuse carries validated semantic context into the deterministic result")

    with tempfile.TemporaryDirectory(prefix="anvil-coverage-scope-") as temporary:
        scoped_source = Path(temporary) / "grouped-coverage.csv"
        scoped_source.write_text("period,segment,metric,eligible,evaluated\n"
                                 "2026-01,a,10,100,90\n2026-01,b,20,100,50\n"
                                 "2026-02,a,11,100,90\n2026-02,b,21,100,50\n", encoding="utf-8")
        scoped_profile = profile_file(scoped_source)
        scoped_plan = validate_analysis_plan({"schema_version": 1, "source_sha256": scoped_profile["source"]["sha256"],
            "depth": "FAST", "primary_question": "Are segment comparisons coverage-aligned?", "questions": [],
            "operations": [
                {"id": "segment-delta", "operation": "delta", "column": "metric", "period_column": "period",
                 "baseline": "2026-01-01", "current": "2026-02-01", "group_by": ["segment"]},
                {"id": "overall-coverage", "operation": "coverage", "column": "evaluated", "denominator": "eligible",
                 "group_by": ["period"]}],
            "budgets": {"max_rows": 20, "max_groups": 10}})
        scoped_execution = execute_plan(str(scoped_source), scoped_plan, profile=scoped_profile)
        scoped_claim = validate_claims([{"id": "C-scoped", "statement": "Segment metrics have stable coverage.",
            "classification": "DERIVED", "claim_type": "period_comparison", "confidence": "HIGH",
            "evidence_ids": ["E-scoped"], "operation_id": "segment-delta"}], evidence_ids={"E-scoped"},
            plan=scoped_plan, execution=scoped_execution)[0]
        check(scoped_claim["validation"]["status"] == "UNKNOWN" and scoped_claim["confidence"] == "UNKNOWN",
              "overall coverage is not incorrectly used to validate segment-level comparisons")

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
                       "analysis_context": profile["semantic_context"], "execution": result,
                       "execution_metadata": result["execution_metadata"],
                       "evidence": ev, "findings": findings[:1],
                       "claims": [
                           {"id": "C-rows", "statement": "The source contains six observations.", "classification": "DERIVED",
                            "claim_type": "observation_count", "confidence": "HIGH", "evidence_ids": ["E-data"],
                            "operation_id": "row-count", "population": {"basis": "rows", "count": 6}},
                           {"id": "C-owners", "statement": "Three distinct owners are represented.", "classification": "DERIVED",
                            "claim_type": "entity_count", "confidence": "MEDIUM", "evidence_ids": ["E-data"],
                            "operation_id": "owners", "population": {"basis": "distinct_key", "count": 3, "key_fields": ["owner"]}},
                           {"id": "C-wrong-grain", "statement": "There are six entities.", "classification": "DERIVED",
                            "claim_type": "entity_count", "confidence": "HIGH", "evidence_ids": ["E-data"],
                            "operation_id": "row-count", "population": {"basis": "rows", "count": 6, "key_fields": ["entity"]}},
                           {"id": "C-trend", "statement": "Latency has a three-period trend.", "classification": "DERIVED",
                            "claim_type": "trend", "confidence": "MEDIUM", "evidence_ids": ["E-data"], "operation_id": "latency-trend"},
                           {"id": "C-cause", "statement": "Volume caused latency to improve.", "classification": "DERIVED",
                            "claim_type": "causal", "confidence": "LOW", "evidence_ids": ["E-data"], "operation_id": "volume-latency-correlation"}],
                       "hypotheses": [{"id": "H-coverage", "question": "Did coverage affect the observed movement?",
                                       "explanation": "Coverage remains an unresolved alternative.", "status": "UNKNOWN",
                                       "confidence": "UNKNOWN", "evidence_ids": [], "limitations": ["No verified coverage measure."]}],
                       "narrative": {"main_conclusion": "The result is evidence linked and includes a hypothesis only as a hypothesis.",
                                     "what_changed": ["Volume rose in the selected periods."], "explanation": [],
                                     "unresolved": ["The hypothesis needs additional evidence."], "risks_opportunities": [],
                                     "next_actions": [], "finding_ids": ["F-a"]}, "limitations": ["Synthetic test data."]}
    checked = validate_result(analysis_result)
    components = artifact_components(analysis_result)
    check(components["evidence"][0]["data"] == operations["volume-change"]
          and components["findings"][0]["epistemic"] == "HYPOTHESIS"
          and checked["materiality_tiers"] == [["F-a"]]
          and {claim["id"]: claim["validation"]["status"] for claim in checked["claims"]} == {
              "C-rows": "VALIDATED", "C-owners": "QUALIFIED", "C-wrong-grain": "REJECTED",
              "C-trend": "VALIDATED", "C-cause": "REJECTED"}
          and next(claim for claim in checked["claims"] if claim["id"] == "C-owners")["confidence"] == "LOW"
          and next(claim for claim in checked["claims"] if claim["id"] == "C-wrong-grain")["confidence"] == "LOW"
          and checked["hypotheses"][0]["status"] == "UNKNOWN",
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
    benchmark_result = execute_plan(str(benchmark_data), benchmark_plan, profile=benchmark_profile)
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
            benchmark_result = execute_plan(str(benchmark_source), benchmark_plan, profile=benchmark_profile)
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
