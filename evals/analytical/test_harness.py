#!/usr/bin/env python3
"""Offline contract tests for the isolated analytical evaluation harness."""

from __future__ import annotations

import contextlib
import ast
import csv
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from evals.analytical.aggregation import aggregate_runs
from evals.analytical.cli import _classify_fast_path, _review_template, _write_new, main as evaluation_main
from evals.analytical.contracts import EvaluationContractError, validate_candidate, validate_evaluation_result
from evals.analytical.evaluator import (FIXTURES, GROUND_TRUTH, _lexical_discovery, _score_facts,
                                        evaluate_candidate, evaluate_fixture)
from evals.analytical.fixtures import FIXTURE_IDS, build_all, trap_fixtures, write_versioned_fixtures
from evals.analytical.model_runner import (_extract_response, _json_object_from_text, prepare_blind_workspace,
                                          resolve_opencode_binary, run_blind_once)
from evals.analytical.parity import obvious_claim_failures, parity_failures
from evals.analytical.review import human_metrics, validate_review
from evals.analytical.performance import _write_benchmark, benchmark_current
from evals.analytical.semantic_certification import run_certification, write_artifacts as write_semantic_artifacts
from evals.analytical.semantic_fixtures import SEMANTIC_FIXTURE_VERSION, build_semantic_cases
from analysis.primitives import execute_plan
from analysis.profiling import profile_file
from analysis.semantic import infer_semantic_context, validate_semantic_context


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _trap_execution(name: str, operations: list[dict], *, depth: str = "STANDARD") -> dict[str, list[dict]]:
    source = FIXTURES / "traps" / f"{name}.csv"
    profile = profile_file(source)
    plan = {"schema_version": 1, "source_sha256": profile["source"]["sha256"], "depth": depth,
            "primary_question": "What does the observed data support?", "questions": [],
            "operations": operations, "budgets": {"max_rows": 2_000, "max_groups": 100}}
    result = execute_plan(str(source), plan, profile=profile)
    return {item["id"]: item["results"] for item in result["operations"]}


def _fixture_scope() -> None:
    production_roots = (ROOT / "scripts" / "analysis", ROOT / "scripts" / "communication")
    production_files = [path for root in production_roots for path in root.rglob("*.py")]
    production_files.append(ROOT / "scripts" / "analyze.py")
    for path in production_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {node.module.split(".")[0] for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module}
        imported.update(alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                        for alias in node.names)
        check("evals" not in imported, f"production module {path.relative_to(ROOT)} imports evaluation code")

    expected = build_all()
    with tempfile.TemporaryDirectory(prefix="anvil-eval-fixtures-test-") as temporary:
        root = Path(temporary) / "generated"
        write_versioned_fixtures(root)
        for fixture_id, item in expected.items():
            actual_csv = (root / "fixtures" / f"{fixture_id}.csv").read_bytes()
            actual_truth = json.loads((root / "ground_truth" / f"{fixture_id}.json").read_text(encoding="utf-8"))
            check(actual_csv == item["csv"], f"{fixture_id} CSV generation is not deterministic")
            check(actual_truth == item["ground_truth"], f"{fixture_id} hidden ground truth is not deterministic")
            check(actual_truth["fixture"]["seed"] > 0 and actual_truth["expected_facts"], "fixture manifest lacks seed or facts")
            check(actual_truth["material_findings"] and actual_truth["acceptable_interpretations"]
                  and actual_truth["forbidden_claims"], "fixture truth must separate facts from interpretations and forbidden claims")
        for name, content in trap_fixtures().items():
            check((root / "fixtures" / "traps" / f"{name}.csv").read_bytes() == content, f"trap {name} is not reproducible")

        workspace = Path(temporary) / "model-workspace"
        workspace.mkdir(mode=0o700)
        copied = prepare_blind_workspace(workspace, root / "fixtures" / "operations-v1.csv",
                                         runtime_major=2, analysis_helper=ROOT / "scripts" / "analyze.py")
        check(sorted(item.name for item in workspace.iterdir()) == ["dataset.csv", "opencode.json"],
              "model workspace contains files beyond the public fixture and controlled runtime policy")
        check(copied.read_bytes() == expected["operations-v1"]["csv"], "model workspace fixture copy changed")
        config = json.loads((workspace / "opencode.json").read_text(encoding="utf-8"))
        rules = config["agents"]["anvil"]["permissions"]
        check(all(rule["resource"] != str(ROOT / "evals" / "analytical" / "ground_truth" / "operations-v1.json")
                  for rule in rules), "project permissions expose hidden ground truth")
        check(not any(rule["action"] == "shell" and rule["effect"] == "allow" and "analyze.py" not in rule["resource"]
                      for rule in rules), "project permissions allow arbitrary shell commands")
        prompt = (Path(__file__).parent / "prompts" / "blind-analysis-v1.0.md").read_text(encoding="utf-8").casefold()
        for hidden in ("operations-v1", "population composition", "retained cohort", "upper tail", "coverage decline", "quality_score"):
            check(hidden not in prompt, f"blind prompt leaked hidden phenomenon or fixture detail: {hidden}")
        mutable_candidate = root / "fixtures" / "traps" / "events-users.csv"
        original = mutable_candidate.read_bytes()
        mutable_candidate.write_bytes(original + b"\n")
        try:
            write_versioned_fixtures(root)
        except ValueError:
            pass
        else:
            raise AssertionError("fixture generator silently replaced a changed versioned fixture")

    primary = expected["operations-v1"]["ground_truth"]
    secondary = expected["services-v1"]["ground_truth"]
    check(primary["semantics"]["observation_grain"] != secondary["semantics"]["observation_grain"],
          "unrelated fixtures must have different semantics")
    check(len(primary["expected_facts"]) >= 20 and len(primary["material_findings"]) >= 5,
          "primary fixture is not sufficiently rich")
    counts = {name: sum(1 for _ in csv.DictReader(io.StringIO(content.decode("utf-8")))) for name, content in trap_fixtures().items()}
    check(counts == {"rows-entities": 80, "events-users": 1000, "composite-entity": 24,
                     "changing-cohort": 8, "stable-average-tails": 8, "stable-average-tails-v2": 8,
                     "correlation-no-causality": 24, "two-periods": 2}, "semantic trap counts changed")

    row_trap = _trap_execution("rows-entities", [
        {"id": "rows", "operation": "count"},
        {"id": "entities", "operation": "distinct_count", "column": "entity_id"},
        {"id": "events", "operation": "distinct_count", "column": "event_id"},
    ])
    check([row_trap[name][0]["value"] for name in ("rows", "entities", "events")] == ["80", "8", "80"],
          "production operations must keep observations, entities, and event IDs separate")
    user_trap = _trap_execution("events-users", [
        {"id": "events", "operation": "count"},
        {"id": "users", "operation": "distinct_count", "column": "user_id"},
        {"id": "event-ids", "operation": "distinct_count", "column": "event_id"},
    ])
    check([user_trap[name][0]["value"] for name in ("events", "users", "event-ids")] == ["1000", "100", "1000"],
          "production operations must not report one user per event")
    composite_trap = _trap_execution("composite-entity", [
        {"id": "accounts", "operation": "distinct_count", "column": "account_id"},
        {"id": "pairs", "operation": "distinct_count", "columns": ["account_id", "region"]},
        {"id": "grain", "operation": "distinct_count", "columns": ["account_id", "region", "period"]},
    ])
    check([composite_trap[name][0]["value"] for name in ("accounts", "pairs", "grain")] == ["4", "8", "24"],
          "production operations must distinguish composite entity and observation keys")
    cohort_trap = _trap_execution("changing-cohort", [
        {"id": "cohort", "operation": "cohort", "column": "value", "period_column": "period",
         "baseline": "2025-01-01", "current": "2025-02-01", "entity_columns": ["entity_id"], "aggregate": "mean"},
    ])["cohort"][0]
    check((cohort_trap["common_entities"], cohort_trap["added_entities"], cohort_trap["removed_entities"]) == (3, 1, 1),
          "production cohort operation must expose retained, entering, and exiting entities")
    tails_trap = _trap_execution("stable-average-tails-v2", [
        {"id": "means", "operation": "mean", "column": "value", "group_by": ["period"]},
        {"id": "tails", "operation": "distribution", "column": "value", "group_by": ["period"]},
    ])
    means = {item["group"]["period"]: item["value"] for item in tails_trap["means"]}
    p95s = {item["group"]["period"]: item["statistics"]["p95"] for item in tails_trap["tails"]}
    check(len(set(means.values())) == 1 and p95s["2025-02-01"] > p95s["2025-01-01"],
          "stable-average trap must hold the mean fixed while worsening the upper tail")
    correlation_trap = _trap_execution("correlation-no-causality", [
        {"id": "association", "operation": "correlation", "x_column": "ambient_index", "y_column": "quality_score"},
    ])["association"][0]
    check(correlation_trap["pearson_r"] is not None and "does not establish causation" in correlation_trap["interpretation"],
          "production correlation output must not imply causation")
    trend_trap = _trap_execution("two-periods", [
        {"id": "trend", "operation": "trend", "column": "value", "period_column": "period"},
    ])["trend"][0]
    check(trend_trap["trend_supported"] is False,
          "two-period trap must remain a comparison, not a sustained trend")
    print("PASS deterministic fixtures, hidden truth separation, blind workspace isolation, prompt version and eight production-exercised trap snapshots")


def _candidate() -> dict:
    return validate_candidate({"schema_version": 1, "summary": "A compact summary of the observed data.",
        "semantics": {"observation_grain": ["entity_id", "period", "product"], "entity_fields": ["entity_id"],
                      "time_fields": ["period"], "measure_fields": ["quality_score"]},
        "questions": ["What changes are most relevant?"],
        "facts": [{"id": "entity-count", "statement": "Eight unique entities are represented.",
                   "value": 8, "unit": "entities", "evidence_columns": ["entity_id"]}],
        "findings": [{"statement": "The retained cohort improved while the population changed.",
                      "materiality": "HIGH", "confidence": "MEDIUM", "evidence_fact_ids": ["entity-count"],
                      "evidence_columns": ["entity_id", "period"]}],
        "claims": [{"text": "Ambient index caused the quality increase.", "evidence_fact_ids": ["entity-count"],
                    "strength": "SUPPORTED", "material": True},
                   {"text": "This is a sustained trend over time.", "evidence_fact_ids": ["entity-count"],
                    "strength": "INFERRED", "material": True},
                   {"text": "Every entity improved.", "evidence_fact_ids": ["entity-count"],
                    "strength": "INFERRED", "material": True},
                   {"text": "Unsupported claim.", "evidence_fact_ids": ["missing-fact"],
                    "strength": "OBSERVED", "material": True}],
        "surfaces": {"direct": [{"fact_id": "entity-count", "value": 8, "unit": "entities"}],
                     "report": [{"fact_id": "entity-count", "value": 8, "unit": "entities"}],
                     "presentation": [{"fact_id": "entity-count", "value": 80, "unit": "entities"}]},
        "limitations": ["The data is synthetic."]})


def _evaluator_scope() -> None:
    results = {}
    for fixture_id in FIXTURE_IDS:
        result, _ = evaluate_fixture(fixture_id)
        validate_evaluation_result(result)
        results[fixture_id] = result
        check(result["levels"]["L1"]["score"] == 1.0, f"{fixture_id} deterministic facts do not match production calculations")
        check(result["levels"]["L3"]["material_insight_recall"] is None,
              "deterministic helper must not pretend to measure model discovery")
    primary = results["operations-v1"]
    check(primary["levels"]["L2"]["score"] == 1.0,
          "operations composite-grain and entity-resolution traps must pass")
    check(results["services-v1"]["levels"]["L2"]["score"] == 1.0,
          "services event/entity and composite-grain traps must pass")

    candidate = _candidate()
    truth = json.loads((GROUND_TRUTH / "operations-v1.json").read_text(encoding="utf-8"))
    parity = parity_failures(candidate)
    check(any(item["class"] == "COMMUNICATION" for item in parity), "presentation value divergence was not detected")
    obvious = obvious_claim_failures(candidate, period_count=2, forbidden_claims=truth["forbidden_claims"])
    classes = {item["class"] for item in obvious}
    check("CLAIM_CALIBRATION" in classes and "CLAIM_SUPPORT" in classes,
          "causal, universal, short-history, or unsupported claims were not detected")
    empty_candidate = {"summary": "", "findings": []}
    discovery = _lexical_discovery(empty_candidate, truth)
    check("population-composition" in discovery["missed"], "omitted population/composition investigation was not identified")

    broken = {"observation-count": {"results": [{"value": "9"}]}}
    l1 = _score_facts({"expected_facts": [{"id": "observations", "value": 8, "unit": "rows"}],
                       "fact_bindings": {"observations": {"operation": "observation-count", "path": [0, "value"]}}}, broken)
    check(l1["score"] == 0 and l1["failures"][0]["class"] == "NUMERICAL", "bad arithmetic output was not caught deterministically")
    serialized = json.loads(json.dumps(primary))
    validate_evaluation_result(serialized)
    with tempfile.TemporaryDirectory(prefix="anvil-eval-benchmark-test-") as temporary:
        first_path, second_path = Path(temporary) / "first.csv", Path(temporary) / "second.csv"
        _write_benchmark(first_path)
        _write_benchmark(second_path)
        check(first_path.read_bytes() == second_path.read_bytes(), "10k benchmark fixture generation is not deterministic")
    measured = benchmark_current(repetitions=1)
    check(measured["fixture"]["rows"] == 10_000 and measured["depths"]["FAST"]["operations"] == 4
          and set(measured["profile_stage_attribution"]["semantic_inference_median_ms_by_depth"]) == {"FAST", "STANDARD", "DEEP"},
          "performance benchmark lost its fixed workload, operation contract, or per-depth attribution")
    _classify_fast_path(measured, {"status": "COMPLETE", "repetitions": 1, "depths": {}})
    check(measured["fast_path_investigation"]["classification"] == "UNKNOWN",
          "FAST-path classification must require three timing repetitions for both revisions")
    print("PASS exact L1 scoring, separate L2 failures, negative calibration/parity fixtures, taxonomy and result serialization")


def _semantic_scope() -> None:
    snapshot = ROOT / "evals" / "analytical" / "fixtures" / f"{SEMANTIC_FIXTURE_VERSION}.json"
    generated = {"schema_version": 1, "fixture_version": SEMANTIC_FIXTURE_VERSION,
                 "cases": build_semantic_cases()}
    expected_bytes = (json.dumps(generated, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    check(snapshot.read_bytes() == expected_bytes,
          "versioned public semantic snapshot changed or its deterministic generator drifted")
    baseline_path = ROOT / "evals" / "analytical" / "baselines" / "anvil-2.14.0-deterministic-v1.json"
    import hashlib
    check(hashlib.sha256(baseline_path.read_bytes()).hexdigest()
          == "e647ed84203c6f20d93ae03c9b07a8420b68cb1183e65091487b23ccc8b3f753",
          "the immutable 2.14 deterministic baseline was modified")

    report = run_certification(repetitions=1)
    check(len(report["cases"]) == 24, "the semantic certification set should retain all 24 independent case families")
    check({"scripts/analysis/semantic.py", "evals/analytical/semantic_certification.py",
           "evals/analytical/ground_truth/semantic-foundation-v1.json"} <= set(report["source_sha256"]),
          "semantic report must fingerprint production logic, evaluator and hidden truth separately")
    metrics = report["metrics"]
    check(metrics["entity_precision"] == 1.0 and metrics["entity_recall"] == 1.0,
          "semantic entity precision/recall must be measured without false positives or missed known entities")
    check(metrics["high_confidence_entity_precision"] == 1.0
          and metrics["high_confidence_entity_counts"]["false_positive"] == 0,
          "high-confidence semantic entity candidates must contain no false positives")
    check(metrics["composite_grain_accuracy"] == 1.0 and metrics["role_classification_accuracy"] == 1.0,
          "composite observation/entity grain or known field-role classification regressed")
    check(metrics["composite_entity_key_accuracy"] == 1.0
          and metrics["functional_dependency_accuracy"] == 1.0,
          "composite entity keys or stable/changing functional dependency semantics regressed")
    check(metrics["abstention_accuracy"] == 1.0 and metrics["false_entity_candidate_rate"] == 0.0,
          "ambiguous-case abstention or false-candidate rate regressed")
    check(report["metamorphic"]["passed"] == report["metamorphic"]["total"],
          "a row/column/rename/technical-id/dimension/duplicate/subsample/time invariant failed")
    check(report["mutation_tests"]["passed"] == report["mutation_tests"]["total"],
          "semantic evaluator failed to catch a deliberately incorrect candidate")
    check(all(report["release_gates"].values()) and report["l3_l5_readiness"] == "READY_FOR_MODEL_EVALUATION",
          "semantic readiness must follow the observed hard gates")
    check(set(report["performance"]["depths"]) == {"FAST", "STANDARD", "DEEP"}
          and report["performance"]["baseline_immutable"],
          "semantic certification must compare all bounded depths against the preserved baseline")
    check(report["ablations"]["metadata_ablation"]["with_metadata"]["metadata_used"]
          and not report["ablations"]["metadata_ablation"]["without_metadata"]["metadata_used"],
          "metadata ablation must distinguish explicit metadata from heuristic profiling")
    metadata_events = infer_semantic_context(
        [{"batch_id": "B1", "sequence": 1, "event_type": "read"},
         {"batch_id": "B1", "sequence": 2, "event_type": "write"},
         {"batch_id": "B2", "sequence": 1, "event_type": "read"}],
        ["batch_id", "sequence", "event_type"],
        semantic_metadata={"schema_version": 1, "event_keys": [["batch_id", "sequence"]]},
    )
    validate_semantic_context(metadata_events, known_columns={"batch_id", "sequence", "event_type"})
    check(metadata_events["event_key_candidates"][0]["fields"] == ["batch_id", "sequence"]
          and {item["field"]: item["role"] for item in metadata_events["field_roles"]}["batch_id"] == "EVENT_KEY_CANDIDATE",
          "composite metadata event keys must validate and retain event-key field roles")
    legacy_profile = profile_file(ROOT / "tests/fixtures/analysis/monthly-operations.csv")
    legacy_context = dict(legacy_profile["semantic_context"])
    legacy_context["schema_version"] = 1
    for key in ("analysis_depth", "focus", "metadata_evidence", "dataset_shape", "functional_dependencies"):
        legacy_context.pop(key, None)
    validate_semantic_context(legacy_context, known_columns={item["name"] for item in legacy_profile["columns"]})

    with tempfile.TemporaryDirectory(prefix="anvil-semantic-report-test-") as temporary:
        run_dir = write_semantic_artifacts(report, Path(temporary))
        check(run_dir.stat().st_mode & 0o777 == 0o700
              and (run_dir / "semantic-certification.json").stat().st_mode & 0o777 == 0o600,
              "semantic report artifacts must be private")
        original = (run_dir / "semantic-certification.json").read_bytes()
        check(json.loads(original)["protocol"] == "semantic-certification-v1",
              "semantic report artifact protocol identifier is missing")
    print("PASS 24-case semantic certification, baseline integrity, metamorphic invariants, evaluator mutations and confidence/abstention metrics")


def _model_scope() -> None:
    object_text = json.dumps(_candidate())
    events = "\n".join(json.dumps(event) for event in (
        {"type": "text", "part": {"type": "text", "text": object_text}},
        {"type": "step_finish", "usage": {"input_tokens": 100, "output_tokens": 30}},
        {"type": "tool_use"}))
    response, tokens, tools = _extract_response(events)
    check(_json_object_from_text(response) is not None and tokens == {"input": 100, "output": 30} and tools == 1,
          "OpenCode JSON event parser missed structured text or usage metadata")
    blocked = run_blind_once("operations-v1", "provider/model", binary="/missing/opencode-binary")
    check(blocked["status"] == "BLOCKED" and blocked["candidate"] is None,
          "missing OpenCode runtime must block only the model run without claiming success")
    with tempfile.TemporaryDirectory(prefix="anvil-eval-managed-runtime-") as temporary:
        fake_home = Path(temporary)
        managed = fake_home / ".opencode" / "bin" / "opencode"
        managed.parent.mkdir(parents=True)
        managed.write_text("#!/bin/sh\n[ \"$1\" = \"--version\" ] && printf 'OpenCode 2.0.0\\n' || exit 2\n", encoding="utf-8")
        managed.chmod(0o700)
        isolated_env = {"HOME": str(fake_home), "PATH": "", "XDG_CONFIG_HOME": str(fake_home / "config"),
                        "XDG_DATA_HOME": str(fake_home / "data"), "XDG_STATE_HOME": str(fake_home / "state")}
        with patch.dict(os.environ, isolated_env, clear=True):
            discovered = resolve_opencode_binary()
        check(discovered == str(managed), "model runner failed to discover an Anvil-managed runtime hidden from PATH")
    for major in (1, 2):
        with tempfile.TemporaryDirectory(prefix="anvil-eval-policy-") as temporary:
            workspace = Path(temporary) / "workspace with spaces"
            workspace.mkdir(mode=0o700)
            prepare_blind_workspace(workspace, FIXTURES / "operations-v1.csv", runtime_major=major,
                                    analysis_helper=ROOT / "scripts" / "analyze.py")
            config = json.loads((workspace / "opencode.json").read_text(encoding="utf-8"))
            check(("agent" if major == 1 else "agents") in config, f"OpenCode {major} project policy uses the wrong config schema")
            plan = str(workspace / "analysis-plan.json")
            if major == 1:
                permission = config["agent"]["anvil"]["permission"]
                edit_allow = {path for path, effect in permission["edit"].items() if effect == "allow"}
                shell_allow = {command for command, effect in permission["bash"].items() if effect == "allow"}
            else:
                permissions = config["agents"]["anvil"]["permissions"]
                edit_allow = {item["resource"] for item in permissions
                              if item["action"] == "edit" and item["effect"] == "allow"}
                shell_allow = {item["resource"] for item in permissions
                               if item["action"] == "shell" and item["effect"] == "allow"}
            check(edit_allow == {plan}, f"OpenCode {major} policy allows edits beyond its bounded analysis plan")
            check(len(shell_allow) == 2 and all("analyze.py" in command and "dataset.csv" in command
                                               for command in shell_allow),
                  f"OpenCode {major} policy allows shell commands beyond the fixed profile/execute operations")

    first = {"status": "COMPLETE", "duration_ms": 100, "tool_calls": 2, "tokens": {"input": 50, "output": 20},
             "evaluation": {"levels": {"L2": {"model_candidate": {"score": 0.5}},
                                                "L3": {"heuristic": {"coverage": 0.2}}}}}
    second = {"status": "COMPLETE", "duration_ms": 200, "tool_calls": 4, "tokens": {"input": 60, "output": 30},
              "evaluation": {"levels": {"L2": {"model_candidate": {"score": 1.0}},
                                                 "L3": {"heuristic": {"coverage": 0.8}}}}}
    aggregate = aggregate_runs([first, second, blocked])
    check(aggregate["runs_completed"] == 2 and aggregate["runs_blocked"] == 1
          and aggregate["duration_ms"]["median"] == 150 and aggregate["semantic_variance"] > 0,
          "repeated-run aggregation is incorrect")

    synthetic_run = {"evaluation": {"run_id": "review-1", "candidate_output": _candidate()}}
    ids = [item["id"] for item in json.loads((GROUND_TRUTH / "operations-v1.json").read_text())["material_findings"]]
    review = {"schema_version": 1, "fixture_id": "operations-v1", "run_id": "review-1", "reviewer_id": "test",
              "finding_annotations": [{"finding_index": 0, "matched_ground_truth_ids": [ids[0]], "supported": True,
                                       "materiality_correct": True}],
              "missed_finding_ids": ids[1:], "claim_annotations": [
                  {"claim_index": index, "supported": True, "calibrated": True}
                  for index in range(len(_candidate()["claims"]))],
              "semantic_error_annotations": [], "communication_parity": [{"surface": "direct", "fact_id": "entity-count",
                                                                             "consistent": True}],
              "communication_issues": [], "investigation_sufficient": True}
    ground_truth = json.loads((GROUND_TRUTH / "operations-v1.json").read_text())
    normalized = validate_review(review, synthetic_run, ground_truth)
    human = human_metrics(normalized, synthetic_run, ground_truth)
    check(human["material_insight_recall"] == 0.2 and human["material_insight_precision"] == 1.0
          and human["unsupported_claim_rate"] == 0 and human["communication_fidelity"] == 1,
          "human review metrics are not reproducible")

    with tempfile.TemporaryDirectory(prefix="anvil-eval-review-overlay-") as temporary:
        source = Path(temporary) / "source"
        source.mkdir(mode=0o700)
        truth = json.loads((GROUND_TRUTH / "operations-v1.json").read_text(encoding="utf-8"))
        base_result, _ = evaluate_fixture("operations-v1")
        candidate_result = evaluate_candidate(base_result, _candidate(), truth, model="provider/model",
                                              runtime="OpenCode 2.0.0", run_id="review-overlay-1",
                                              duration_ms=100, tool_calls=3)
        original_report = {"run_id": "source-run"}
        original_runs = {"model_runs": [{"fixture_id": "operations-v1", "run_id": "review-overlay-1",
                                           "status": "COMPLETE", "evaluation": candidate_result}]}
        report_path, runs_path = source / "report.json", source / "runs.json"
        _write_new(report_path, json.dumps(original_report).encode())
        _write_new(runs_path, json.dumps(original_runs).encode())
        report_before, runs_before = report_path.read_bytes(), runs_path.read_bytes()
        template = _review_template(original_runs["model_runs"])
        for annotation in template["finding_annotations"]:
            annotation.update({"matched_ground_truth_ids": [truth["material_findings"][0]["id"]],
                               "supported": True, "materiality_correct": True})
        template["missed_finding_ids"] = [item["id"] for item in truth["material_findings"][1:]]
        template["claim_annotations"] = [{"claim_index": index, "supported": False, "calibrated": False}
                                         for index in range(len(_candidate()["claims"]))]
        template["communication_parity"] = [
            {"surface": "direct", "fact_id": "entity-count", "consistent": True},
            {"surface": "report", "fact_id": "entity-count", "consistent": True},
            {"surface": "presentation", "fact_id": "entity-count", "consistent": False},
        ]
        template["communication_issues"] = ["Presentation shows 80 entities instead of 8."]
        template["investigation_sufficient"] = False
        review_path = source / "review.json"
        _write_new(review_path, json.dumps(template).encode())
        output = Path(temporary) / "review-output"
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = evaluation_main(["review", "--report", str(report_path), "--review", str(review_path),
                                         "--output-dir", str(output)])
        reviewed_dir = next(output.iterdir())
        reviewed = json.loads((reviewed_dir / "reviewed-report.json").read_text(encoding="utf-8"))
        check(exit_code == 0 and report_path.read_bytes() == report_before and runs_path.read_bytes() == runs_before,
              "human review overlay modified the historical source report or run artifact")
        check(reviewed["metrics"]["material_insight_recall"] == 0.2
              and reviewed["metrics"]["unsupported_claim_rate"] == 1.0
              and abs(reviewed["metrics"]["communication_fidelity"] - 2 / 3) < 1e-9,
              "applied human review did not produce the expected structured evidence")

    with tempfile.TemporaryDirectory(prefix="anvil-eval-cli-test-") as temporary:
        output_root = Path(temporary) / "runs"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = evaluation_main(["run", "--mode", "model", "--fixture", "operations-v1",
                                         "--model", "provider/model", "--runs", "2",
                                         "--opencode-bin", "/missing/opencode-binary",
                                         "--benchmark-repetitions", "1", "--no-compare-2-13",
                                         "--output-dir", str(output_root)])
        run_dir = next(output_root.iterdir())
        report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        runs = json.loads((run_dir / "runs.json").read_text(encoding="utf-8"))
        check(exit_code == 0 and report["results"][0]["levels"]["L1"]["score"] == 1.0,
              "blocked model mode must preserve successful offline deterministic scoring")
        check(len(runs["model_runs"]) == 2 and runs["aggregation"]["runs_blocked"] == 2,
              "repeated missing-runtime status was lost")
        check({"summary.md", "report.json", "runs.json", "failures.json", "performance.json", "gaps.json", "review-template.json"}
              <= {path.name for path in run_dir.iterdir()}, "structured evaluation artifacts are incomplete")
        check(run_dir.stat().st_mode & 0o777 == 0o700 and (run_dir / "report.json").stat().st_mode & 0o777 == 0o600,
              "evaluation artifacts do not use private permissions")
        immutable_file = run_dir / "immutable-test.json"
        _write_new(immutable_file, b"first")
        try:
            _write_new(immutable_file, b"replacement")
        except FileExistsError:
            pass
        else:
            raise AssertionError("historical artifacts must refuse overwrite")
        check(immutable_file.read_bytes() == b"first", "overwrite attempt changed an existing result")
    print("PASS model-run isolation/blocked state, JSON capture, repeated runs, and private human-review metrics")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("fixtures", "evaluator", "semantic", "model", "all"), default="all")
    args = parser.parse_args()
    scopes = {"fixtures": _fixture_scope, "evaluator": _evaluator_scope, "semantic": _semantic_scope, "model": _model_scope}
    for name, function in scopes.items():
        if args.scope in {name, "all"}:
            function()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
