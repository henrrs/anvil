#!/usr/bin/env python3
"""Offline regression suite for Anvil Communication & Artifact Intelligence."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path
from contextlib import redirect_stdout
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from communication import inputs
from communication.contracts import validate_artifact
from communication.cli import main as communication_main
from communication.diagrams import render_svg, write_svg
from communication.editorial import critique_plan
from communication.errors import CommunicationError
from communication.materialize import render_markdown, write_markdown
from communication.planning import audience_emphasis, extract_explicit_constraints, validate_plan
from communication.quantitative import analyze_metric, analyze_payload, distribution_summary, format_metric, format_number, rank_insights
from communication.review import review_diagram_file, review_markdown


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def expect_code(code: str, fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except CommunicationError as exc:
        check(exc.code == code, f"expected {code}, received {exc.code}: {exc}")
    else:
        raise AssertionError(f"expected CommunicationError {code}")


def metric(identifier: str, baseline, current, *, unit="USD", kind="amount", semantics="lower_is_better", **extra):
    return analyze_metric({"id": identifier, "name": identifier, "unit": unit, "kind": kind,
                           "semantics": semantics, "baseline": baseline, "current": current, **extra})


def evidence(identifier: str, claim: str) -> dict:
    return {"id": identifier, "claim": claim, "epistemic": "MEASUREMENT", "confidence": "HIGH",
            "source": {"type": "fixture", "locator": f"fixture://{identifier}"}}


def make_plan(insights=None, *, artifact="presentation", constraints=None):
    insights = json.loads(json.dumps(insights or []))
    ev = [evidence("E-spend-before", "Spend was USD 1,200,000 in the previous 30 days."),
          evidence("E-spend-now", "Spend was USD 870,000 in the last 30 days."),
          evidence("E-rate-before", "Success rate was 4 percent."),
          evidence("E-rate-now", "Success rate was 2 percent.")]
    known = {item["id"] for item in ev}
    for item in insights:
        for observation in (item.get("baseline"), item.get("current")):
            for ref in (observation or {}).get("evidence_ids", []):
                if ref not in known:
                    ev.append(evidence(ref, f"Supporting measurement {ref}."))
                    known.add(ref)
        normalization = item.get("normalization") or {}
        for field in ("baseline_denominator_evidence_ids", "current_denominator_evidence_ids"):
            for ref in normalization.get(field, []):
                if ref not in known:
                    ev.append(evidence(ref, f"Supporting normalized denominator {ref}."))
                    known.add(ref)
    finding = {"id": "F-spend", "claim": "Monthly spend decreased while retaining the same unit.",
               "epistemic": "INFERENCE", "confidence": "HIGH", "evidence_ids": ["E-spend-before", "E-spend-now"],
               "implications": [], "limitations": [], "relevance": {"executive": "high", "technical": "high"},
               "quantitative_insight_ids": [item["id"] for item in insights]}
    selected_constraints = constraints if constraints is not None else [
        {"kind": "exact_slides", "value": 5, "strength": "hard", "origin": "explicit"},
        {"kind": "cover_count", "value": 1, "strength": "hard", "origin": "explicit"},
        {"kind": "content_count", "value": 3, "strength": "hard", "origin": "explicit"},
        {"kind": "architecture_count", "value": 1, "strength": "hard", "origin": "explicit"},
    ] if artifact == "presentation" else []
    plan = {"schema_version": 1,
            "request": {"artifact": artifact, "audience": "executive", "purpose": "Explain material operational changes.",
                        "tone": "direct", "language": "en", "minutes": 10, "constraints": selected_constraints},
            "title": "Operational performance improved with lower spend",
            "thesis": "Spend declined materially; rate and architecture need separate interpretation.",
            "evidence": ev, "findings": [finding], "quantitative_insights": insights,
            "storyline": [{"title": "Spend fell over the observed window", "finding_ids": ["F-spend"], "rationale": "Lead with impact."}],
            "selection_rationale": ["Selected the measured period comparison."], "exclusions": [],
            "sections": ([{"title": "Measured change", "body": "The observed comparison supports this summary.",
                           "finding_ids": ["F-spend"], "evidence_ids": [],
                           "insight_ids": [item["id"] for item in insights]}] if artifact != "presentation" else []),
            "slides": ([{"role": "cover", "title": "Operational performance improved", "body": "Decision brief.", "finding_ids": [], "evidence_ids": [], "insight_ids": []},
                        {"role": "content", "title": "Spend declined across the latest month", "body": "The measured comparison is lower.", "finding_ids": ["F-spend"], "evidence_ids": [], "insight_ids": [item["id"] for item in insights if item["id"] == "QI-spend"]},
                        {"role": "content", "title": "Success rate changed by two points", "body": "Interpret the rate movement separately.", "finding_ids": [], "evidence_ids": [], "insight_ids": [item["id"] for item in insights if item["id"] == "QI-success-rate"]},
                        {"role": "content", "title": "Evidence supports a bounded conclusion", "body": "The plan preserves the measurement period.", "finding_ids": ["F-spend"], "evidence_ids": [], "insight_ids": []},
                        {"role": "architecture", "title": "Architecture remains an explicit view", "body": "Current components are shown in a separate view.", "finding_ids": [], "evidence_ids": [], "insight_ids": []}] if artifact == "presentation" else []),
            "architecture_relevant": artifact == "presentation"}
    return plan


def run() -> None:
    fixture = json.loads((ROOT / "tests/fixtures/communication/quantitative-cases.json").read_text())
    amounts = analyze_payload(fixture)["quantitative_insights"]
    spend, rate = amounts
    check(spend["absolute_change"] == "-330000" and spend["relative_change"] == "-27.5", "1.2m to 870k arithmetic")
    check(rate["absolute_change"] == "-2" and rate["percentage_point_change"] == "-2" and rate["relative_change"] == "-50", "rate points and relative percent remain distinct")
    check(rate["interpretation"] == "unfavorable", "direction is interpreted using metric semantics")

    simple = metric("QI-basic", {"value": "100"}, {"value": "80"})
    check(simple["absolute_change"] == "-20" and simple["relative_change"] == "-20", "100 to 80 delta")
    for base in ("0", "0.0000000000001", "-100"):
        item = metric("QI-boundary", {"value": base}, {"value": "10"})
        check(item["relative_change"] is None and item["absolute_change"] is not None, f"safe relative delta for baseline {base}")
    projected = metric("QI-projection", {"value": "100", "evidence_ids": ["E-a"]},
                       {"value": "80", "evidence_ids": ["E-b"]},
                       annualize={"period_days": 14, "assumption": "The two-week reduction persists for one year."})
    check(projected["projection"]["epistemic"] == "PROJECTION" and projected["projection"]["value"] == "-521.4285714285714285714285714", "annualized projection is explicit and deterministic")
    check(any("fewer than 30" in item for item in projected["warnings"]), "short projection window is qualified")

    normalized = metric("QI-normalized", {"value": "100", "evidence_ids": ["E-a"]},
                        {"value": "120", "evidence_ids": ["E-b"]},
                        normalization={"name": "cost per job", "unit": "USD/job", "denominator_unit": "job",
                                       "baseline_denominator": "100", "current_denominator": "150",
                                       "baseline_denominator_evidence_ids": ["E-job-before"],
                                       "current_denominator_evidence_ids": ["E-job-now"]})
    check(normalized["relative_change"] == "20" and normalized["normalization"]["relative_change"] == "-20", "raw total and normalized change answer different questions")
    check("Normalized cost per job: 1.00 → 0.80 USD/job (-20.0% relative)" in format_metric(normalized, audience="technical"), "technical communication retains normalized change")
    normalized_plan = make_plan([normalized], artifact="report")
    validated_normalized = validate_plan(normalized_plan)
    check(validated_normalized["quantitative_insights"][0]["normalization"]["baseline_denominator_evidence_ids"] == ["E-job-before"],
          "normalization denominator provenance survives plan validation")
    estimated = metric("QI-estimated", {"value": "100", "epistemic": "ESTIMATE", "evidence_ids": ["E-a"]},
                       {"value": "80", "epistemic": "MEASUREMENT", "evidence_ids": ["E-b"]})
    unknown_metric = metric("QI-unknown", {"value": "100", "epistemic": "UNKNOWN"},
                            {"value": "80", "epistemic": "MEASUREMENT", "evidence_ids": ["E-b"]})
    check(estimated["epistemic"] == "ESTIMATE" and unknown_metric["epistemic"] == "UNKNOWN" and unknown_metric["interpretation"] == "unknown",
          "derived values preserve estimate and unknown status")
    check("Estimated:" in format_metric(estimated, audience="executive"), "estimated deltas remain visibly qualified")
    expect_code("UNIT_MISMATCH", metric, "QI-bad-unit", {"value": "2"}, {"value": "1"},
                normalization={"name": "bad", "unit": "USD", "denominator_unit": "job", "baseline_denominator": 1, "current_denominator": 1})

    dist = distribution_summary([1, 2, 3, 4, 100, None], unit="ms")
    stats = dist["statistics"]
    check(stats["mean"] == "22" and stats["median"] == "3" and stats["p95"] == "80.8", "mean, median and percentile preserve different distribution facts")
    check(dist["missing_count"] == 1 and dist["outliers"] == [{"value": "100", "count": 1}], "missing and outlier remain visible")
    excluded = distribution_summary([1, 2, 3, 4, 100], unit="ms", exclusions=[{"index": 4, "reason": "known instrumentation defect"}])
    check(excluded["count"] == 4 and excluded["excluded"][0]["reason"] == "known instrumentation defect", "exclusions require and preserve a reason")
    estimated_dist = distribution_summary([1, 2, 3], unit="ms", epistemic="ESTIMATE")
    check(estimated_dist["epistemic"] == "ESTIMATE", "distribution summaries preserve estimated source status")

    ranked = [metric("A", {"value": "100"}, {"value": "90"}),
              metric("B", {"value": "10"}, {"value": "8"})]
    check(rank_insights(ranked, "absolute_impact")[0]["id"] == "A", "absolute impact ranking")
    check(rank_insights(ranked, "relative_improvement")[0]["id"] == "B", "relative improvement ranking")
    expect_code("UNIT_MISMATCH", rank_insights,
                [ranked[0], metric("C", {"value": "10", "unit": "jobs"}, {"value": "8", "unit": "jobs"}, unit="jobs")], "absolute_impact")
    # Audience policy changes emphasis/wording but never rewrites the quantitative result.
    insight_before = json.dumps(analyze_payload(fixture), sort_keys=True)
    emphases = [audience_emphasis(audience, spend)["focus"] for audience in ("executive", "technical", "mixed")]
    check(len(set(emphases)) == 3 and json.dumps(analyze_payload(fixture), sort_keys=True) == insight_before, "audience changes communication policy, not evidence values")
    executive_spend = format_metric(spend, audience="executive")
    technical_spend = format_metric(spend, audience="technical")
    financial_spend = format_metric(spend, audience="financial")
    check("~1.2M USD → ~870k USD" in executive_spend and "Baseline 1200000 USD" in technical_spend
          and "observed actual: ~1.2M → ~870k USD" in financial_spend,
          "audience changes numerical framing while preserving raw values")
    rate_statement = format_metric(rate, audience="executive")
    check("2.0 percentage points" in rate_statement and "-50.0% relative" in rate_statement and "% decrease" not in rate_statement,
          "rate narrative separates percentage-point and relative-percent changes")
    check(format_number("1234567.895", locale="pt-BR", decimals=2) == "1.234.567,90", "locale rounding and grouping")

    prompt_constraints = extract_explicit_constraints("Prepare exactly five slides, measured values only.")
    check([item["kind"] for item in prompt_constraints] == ["exact_slides", "no_estimates"], "natural-language hard constraints detected")
    plan = make_plan(amounts)
    checked = validate_plan(plan)
    check(checked["communication_budget"]["audience"] == "executive" and checked["quality_gates"]["semantic_claim_review"] == "PENDING_MODEL", "plan separates mechanical and semantic gates")
    check(sum(slide["role"] == "architecture" for slide in checked["slides"]) == 1, "exact five-slide role allocation")

    scenario = metric("QI-scenario", {"value": "100", "epistemic": "SCENARIO", "evidence_ids": ["E-scenario-before"]},
                      {"value": "80", "epistemic": "SCENARIO", "evidence_ids": ["E-scenario-now"]})
    check(scenario["epistemic"] == "SCENARIO" and "Scenario:" in format_metric(scenario, audience="executive"),
          "scenario values remain visibly distinct from measured outcomes")

    editorial_fixtures = json.loads((ROOT / "tests/fixtures/communication/editorial-cases.json").read_text())
    refinement_cases = json.loads((ROOT / "tests/fixtures/communication/editorial-refinement-cases.json").read_text())
    refinement_ids = [case["id"] for case in refinement_cases["cases"]]
    check(refinement_cases["evaluation_kind"] == "model_judgment_scenarios"
          and len(refinement_ids) == 11 and len(set(refinement_ids)) == 11
          and all(case.get("evidence") and case.get("context") and case.get("expected_judgment")
                  for case in refinement_cases["cases"]),
          "editorial-context evaluation cases must keep evidence, context and intended judgment explicit")
    for case in editorial_fixtures["cases"]:
        insight = analyze_metric({"id": f"QI-{case['id']}", "name": case["id"], "kind": case["kind"],
                                  "unit": case["unit"], "semantics": case["semantics"], "confidence": "LOW",
                                  "baseline": {"value": case["baseline"], "evidence_ids": [f"E-{case['id']}-before"]},
                                  "current": {"value": case["current"], "evidence_ids": [f"E-{case['id']}-now"]}})
        candidate = make_plan([insight], artifact="report")
        candidate["request"]["audience"] = case["audiences"][0]
        candidate["title"] = case["primary_message"]
        candidate["sections"][0]["title"] = case["primary_message"]
        candidate["sections"][0]["visual_intent"] = {
            "relationship": case["relationship"], "form": case["form"],
            "primary_message": case["primary_message"],
            "primary_evidence_ids": [f"E-{case['id']}-before"],
            "secondary_evidence_ids": [f"E-{case['id']}-now"],
            "prominence": "dominant", "color_roles": ["observed", "scenario"] if case["id"] == "executive_financial_pilot" else ["neutral"],
            "motion": ({"mode": "animated", "purpose": "state_change", "states": [
                {"id": "validated", "label": "Validated", "change": "Validation succeeds.",
                 "new_information": "The request can proceed.", "evidence_ids": [f"E-{case['id']}-before"]},
                {"id": "executed", "label": "Executed", "change": "Execution completes.",
                 "new_information": "The result becomes available.", "evidence_ids": [f"E-{case['id']}-now"]}]}
                       if case["motion"] else {"mode": "static"}),
        }
        original_values = json.dumps(candidate["quantitative_insights"], sort_keys=True)
        transformed = validate_artifact(candidate)
        critic = critique_plan(candidate)
        check(transformed["request"]["audience"] == case["audiences"][0]
              and critic["visual_intent_coverage"] == {"modeled_pages": 1, "total_pages": 1},
              f"{case['id']} evaluation has a validated audience-specific semantic visual plan")
        statement_a = format_metric(insight, audience=case["audiences"][0])
        statement_b = format_metric(insight, audience=case["audiences"][1])
        check(statement_a != statement_b and json.dumps(candidate["quantitative_insights"], sort_keys=True) == original_values,
              f"{case['id']} audience transformation changes communication but not analytical values")
        if case["motion"]:
            rendered, render_result = render_markdown(candidate)
            check("static renderer fallback" in rendered and render_result["fallbacks"],
                  "semantic motion storyboard degrades to an explicit static fallback")
            check(any(signal["code"] == "STATIC_RENDERER_FALLBACK" for signal in render_result["editorial_critic"]["candidate_signals"]),
                  "critic identifies the static renderer limitation")
            repeated_information = deepcopy(candidate)
            repeated_states = repeated_information["sections"][0]["visual_intent"]["motion"]["states"]
            repeated_states[1]["new_information"] = repeated_states[0]["new_information"]
            expect_code("MOTION_NOT_SEMANTIC", validate_artifact, repeated_information)
            repeated_change = deepcopy(candidate)
            repeated_states = repeated_change["sections"][0]["visual_intent"]["motion"]["states"]
            repeated_states[1]["change"] = repeated_states[0]["change"]
            check(any(signal["code"] == "DECORATIVE_MOTION"
                      for signal in critique_plan(repeated_change)["candidate_signals"]),
                  "critic flags repetitive state changes as decorative motion")
        if case["id"] == "executive_financial_pilot":
            candidate["sections"][0]["visual_intent"]["color_roles"] = ["#ff0000"]
            expect_code("CONTRACT_INVALID", validate_artifact, candidate)
    broken = make_plan(amounts)
    broken["slides"].pop()
    expect_code("CONSTRAINT_CONFLICT", validate_plan, broken)
    conflict = make_plan(amounts, constraints=[
        {"kind": "exact_slides", "value": 5, "strength": "hard", "origin": "explicit"},
        {"kind": "exact_slides", "value": 6, "strength": "hard", "origin": "explicit"}])
    expect_code("CONSTRAINT_CONFLICT", validate_plan, conflict)
    measured = make_plan([projected], artifact="report", constraints=[{"kind": "measured_only", "value": True, "strength": "hard", "origin": "explicit"}])
    expect_code("CONSTRAINT_CONFLICT", validate_plan, measured)
    measured_scenario = make_plan([scenario], artifact="report", constraints=[{"kind": "measured_only", "value": True, "strength": "hard", "origin": "explicit"}])
    expect_code("CONSTRAINT_CONFLICT", validate_plan, measured_scenario)
    observed = metric("QI-observed", {"value": "10", "epistemic": "OBSERVED", "evidence_ids": ["E-observed-before"]},
                      {"value": "8", "epistemic": "OBSERVED", "evidence_ids": ["E-observed-now"]})
    observed_plan = make_plan([observed], artifact="report", constraints=[{"kind": "measured_only", "value": True, "strength": "hard", "origin": "explicit"}])
    check(validate_plan(observed_plan)["quality_gates"]["constraints"] == "PASS",
          "measured-only policy accepts observed and deterministically derived values")
    conditional = make_plan(amounts, constraints=[{"kind": "architecture_if_relevant", "value": True, "strength": "hard", "origin": "explicit"}])
    conditional["architecture_relevant"] = False
    conditional["request"]["architecture_relevant"] = False
    conditional["slides"] = [slide for slide in conditional["slides"] if slide["role"] != "architecture"]
    conditional["request"]["constraints"][0]["value"] = True
    conditional["architecture_relevant"] = True
    conditional["request"]["architecture_relevant"] = True
    expect_code("CONSTRAINT_CONFLICT", validate_plan, conditional)
    tampered = make_plan(amounts)
    tampered["quantitative_insights"][0]["absolute_change"] = "-320000"
    expect_code("QUANTITATIVE_ANALYSIS_INVALID", validate_artifact, tampered)
    unsupported_ref = make_plan(amounts)
    unsupported_ref["findings"][0]["evidence_ids"] = ["E-missing"]
    expect_code("CONTRACT_INVALID", validate_artifact, unsupported_ref)

    markdown, render_result = render_markdown(plan)
    check(markdown.count("## Slide ") == 5 and "Evidence and provenance" in markdown, "Markdown slide outline keeps exact count and source appendix")
    check("[E-spend-before](#e-spend-before)" in markdown, "quantitative source citations survive materialization")
    check(render_result["quality_gates"]["semantic_claim_review"] == "PENDING_MODEL", "renderer does not claim semantic truth")
    review = review_markdown(markdown, plan_raw=plan)
    check(review["status"] != "FAIL", "generated Markdown passes deterministic review")
    check(review["quality_gates"]["editorial_review"] == "PENDING_MODEL", "editorial reviewer keeps semantic judgments pending")
    rate_plan = make_plan([rate], artifact="report")
    pp_review = review_markdown("## Rate change\n\nRate changed by -2.0%.\n", plan_raw=rate_plan)
    check(any(item["code"] == "PERCENTAGE_POINT_MISLABELLED" for item in pp_review["findings"]), "review catches percentage-point regression")
    projection_plan = make_plan([projected], artifact="report")
    projection_review = review_markdown("## Measured change\n\nThe projection assumes it will continue.", plan_raw=projection_plan)
    check(any(item["code"] == "PROJECTION_UNQUALIFIED" for item in projection_review["findings"]), "review catches unqualified projection")
    generic_review = review_markdown("## Slide 1 — Overview\n\nSummary.\n")
    check(any(item["code"] == "GENERIC_TITLE" for item in generic_review["findings"]), "review catches generic slide title")

    selective = make_plan(amounts)
    selective["editorial"] = {"decision": "Decide whether to expand the pilot while retaining a success-rate guardrail.",
                              "materiality_note": "Spend fell materially, but the observed rate decline should remain visible.",
                              "appendix_insight_ids": ["QI-success-rate"]}
    selective["slides"][2]["insight_ids"] = []
    selective["slides"][2]["evidence_ids"] = ["E-rate-before", "E-rate-now"]
    selective["slides"][2]["title"] = "Success rate remains the guardrail for scale"
    selective["slides"][2]["body"] = "Keep the observed rate movement in the decision review; inspect its underlying comparison in supporting analysis."
    selective_output, _ = render_markdown(selective)
    appendix = selective_output.split("## Appendix — Supporting analysis", 1)[1]
    check("## Decision context" in selective_output and "## Materiality" in selective_output
          and "**QI-success-rate:**" in appendix and "E-rate-now" in selective_output,
          "editorial reduction moves detail to appendix while retaining source evidence")
    benchmark_root = ROOT / "tests/fixtures/communication"
    benchmark_plan = json.loads((benchmark_root / "communication-benchmark-plan.json").read_text())
    baseline_artifact = (benchmark_root / "baseline-v2.10-quantitative.md").read_text()
    candidate_artifact, candidate_meta = render_markdown(benchmark_plan)
    candidate_reference = (benchmark_root / "candidate-v2.11-editorial.md").read_text()
    exact_amount = baseline_artifact.count("330,000.00 USD")
    compact_amount = candidate_artifact.count("~330k USD")
    check(exact_amount == 2 and compact_amount == 1 and candidate_artifact.count("## Slide ") == 5
          and "## Appendix — Supporting analysis" in candidate_artifact
          and all(item["id"] in candidate_artifact for item in benchmark_plan["evidence"])
          and candidate_meta["editorial_critic"]["status"] == "PENDING_MODEL_REVIEW"
          and "## Slide " in candidate_reference,
          "Anvil quantitative fixture reduces repeated precision, promotes decision context, and retains evidence")
    with tempfile.TemporaryDirectory(prefix="anvil-editorial-cli-") as temporary:
        plan_path = Path(temporary) / "plan.json"
        plan_path.write_text(json.dumps(selective), encoding="utf-8")
        captured = io.StringIO()
        with redirect_stdout(captured):
            exit_code = communication_main(["critique", str(plan_path), "--format", "json"])
        critique = json.loads(captured.getvalue())
        check(exit_code == 0 and critique["status"] == "PENDING_MODEL_REVIEW"
              and critique["audience_profile"]["audience"] == "executive",
              "editorial critic is available through the local artifact CLI")

    with tempfile.TemporaryDirectory(prefix="anvil-communication-") as temporary:
        root = Path(temporary)
        txt = root / "notes.md"
        txt.write_text("one\ntwo\nthree\n", encoding="utf-8")
        csv_path = root / "metrics.csv"
        csv_path.write_text("name,value\nlatency,12\n", encoding="utf-8")
        json_path = root / "data.json"
        json_path.write_text('{"ok": true}', encoding="utf-8")
        inventory = inputs.discover([str(root)], recursive=False)
        check(len(inventory["sources"]) == 3 and all("content" not in source for source in inventory["sources"]), "discovery is metadata-only")
        extracted = inputs.extract(str(txt), start_line=2, end_line=3)
        check(extracted["content"] == "two\nthree" and extracted["source"]["sha256"], "text range extraction preserves provenance")
        check("latency" in inputs.extract(str(csv_path))["content"], "CSV extraction")
        check('"ok": true' in inputs.extract(str(json_path))["content"], "JSON extraction")
        check(inputs.discover([str(root)], recursive=True)["limits"]["max_files"] == 200, "recursive discovery stays bounded")
        expect_code("INPUT_LIMIT_EXCEEDED", inputs.discover, [str(root)], recursive=True, max_files=2)
        oversized = root / "oversized.md"
        with oversized.open("wb") as stream:
            stream.truncate(inputs.MAX_SOURCE_BYTES + 1)
        ignored_large = inputs.discover([str(oversized)])["ignored"]
        check(ignored_large and "exceeds" in ignored_large[0]["reason"], "oversized sources are rejected before reading their contents")
        link = root / "link.md"
        try:
            link.symlink_to(txt)
            check(inputs.discover([str(link)])["ignored"][0]["reason"].startswith("symbolic links"), "symlinks are excluded")
        except (OSError, NotImplementedError):
            pass
        with zipfile.ZipFile(root / "word.docx", "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Doc text</w:t></w:r></w:p></w:body></w:document>')
        check("Doc text" in inputs.extract(str(root / "word.docx"))["content"], "DOCX paragraph extraction")
        with zipfile.ZipFile(root / "deck.pptx", "w") as archive:
            archive.writestr("ppt/presentation.xml", '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId1"/></p:sldIdLst></p:presentation>')
            archive.writestr("ppt/_rels/presentation.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="slide" Target="slides/slide1.xml"/><Relationship Id="rId2" Type="slide" Target="slides/slide2.xml"/></Relationships>')
            archive.writestr("ppt/slides/slide1.xml", '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>Slide text one</a:t></p:sld>')
            archive.writestr("ppt/slides/slide2.xml", '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>Slide text two</a:t></p:sld>')
        pptx_text = inputs.extract(str(root / "deck.pptx"))["content"]
        check(pptx_text.index("[Slide 1] Slide text two") < pptx_text.index("[Slide 2] Slide text one"), "PPTX extraction follows the declared slide order")
        with zipfile.ZipFile(root / "book.xlsx", "w") as archive:
            archive.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Cell text</t></is></c></row></sheetData></worksheet>')
        check("Cell text" in inputs.extract(str(root / "book.xlsx"))["content"], "XLSX cell text extraction")
        pdf_path = root / "sample.pdf"
        pdf_path.write_bytes(b"bounded")
        with mock.patch.object(inputs.shutil, "which", return_value=None):
            expect_code("RENDERER_UNAVAILABLE", inputs.extract, str(pdf_path))
        output = root / "out.md"
        written = write_markdown(plan, output)
        check(output.is_file() and written["bytes"] == output.stat().st_size and stat.S_IMODE(output.stat().st_mode) == 0o600, "Markdown is written atomically with private mode")
        expect_code("MATERIALIZATION_FAILED", write_markdown, plan, output)
        write_markdown(plan, output, force=True)

        diagram = {"schema_version": 1, "id": "D-flow", "title": "Query routing", "question": "How are queries routed?",
                   "viewpoint": "data_flow", "abstraction": "L2", "evidence": [evidence("E-architecture", "The router selects a provider.")],
                   "nodes": [{"id": "Router", "label": "Router", "kind": "service", "role": "PRIMARY", "state": "current", "evidence_ids": ["E-architecture"]},
                             {"id": "Trino", "label": "Trino", "kind": "engine", "role": "COMPUTE", "state": "current", "evidence_ids": ["E-architecture"]},
                             {"id": "History", "label": "Query History", "kind": "store", "role": "DATA", "state": "current", "evidence_ids": ["E-architecture"]}],
                   "edges": [{"id": "route", "from": "Router", "to": "Trino", "relation": "routes to", "role": "CONTROL", "evidence_ids": ["E-architecture"]}],
                   "layout": {"canvas": {"width": 1200, "height": 700},
                              "nodes": {"Router": {"x": 80, "y": 300, "width": 180, "height": 80},
                                        "Trino": {"x": 920, "y": 300, "width": 180, "height": 80},
                                        "History": {"x": 500, "y": 285, "width": 180, "height": 110}}}}
        expect_code("LAYOUT_INVALID", render_svg, diagram)
        diagram["layout"]["nodes"]["History"]["y"] = 500
        svg, validated_diagram = render_svg(diagram)
        check("aria-labelledby" in svg and "<title" in svg and validated_diagram["quality_gates"]["layout"] == "PASS", "SVG carries accessible semantics")
        svg_path = root / "diagram.svg"
        write_svg(diagram, svg_path)
        checked_svg = review_diagram_file(svg_path, diagram)
        check(checked_svg["status"] == "PASS_WITH_WARNINGS" and checked_svg["quality_gates"]["semantic_claim_review"] == "PENDING_MODEL", "SVG review reports semantic review as pending")
        check(checked_svg["quality_gates"]["visual_qa"] == "PASS", "SVG reviewer reports measurable geometry QA")
        unmodeled_svg = review_diagram_file(svg_path)
        check(unmodeled_svg["status"] == "PASS_WITH_WARNINGS", "SVG review does not imply layout proof without the model")
        check(unmodeled_svg["quality_gates"]["visual_qa"] == "PASS_GEOMETRY_ONLY", "model-free SVG review states its geometry-only scope")
        root = ET.fromstring(svg)
        edge = next(item for item in root.iter() if item.tag.endswith("polyline"))
        edge.set("points", "-40,300 1240,300")
        svg_path.write_bytes(ET.tostring(root, encoding="utf-8"))
        expect_code("OUTPUT_VALIDATION_FAILED", review_diagram_file, svg_path)
        write_svg(diagram, svg_path, force=True)
        outside_route = dict(diagram)
        outside_route["edges"] = [{"id": "route", "from": "Router", "to": "Trino", "relation": "routes to",
                                    "role": "CONTROL", "evidence_ids": ["E-architecture"],
                                    "points": [[170, 340], [-20, 350], [1010, 340]]}]
        expect_code("LAYOUT_INVALID", render_svg, outside_route)
        boundary = dict(diagram)
        boundary["boundaries"] = [{"id": "inside", "label": "Internal", "kind": "trust zone", "role": "SECURITY", "node_ids": ["Router"]}]
        boundary["layout"] = {**diagram["layout"], "boundaries": {"inside": {"x": 60, "y": 270, "width": 220, "height": 140}}}
        render_svg(boundary)
        boundary["layout"]["boundaries"]["inside"] = {"x": 60, "y": 270, "width": 180, "height": 80}
        expect_code("LAYOUT_INVALID", render_svg, boundary)

    print("PASS Anvil Communication & Artifact Intelligence arithmetic, evidence, planning, inputs, rendering, diagrams, and review")


if __name__ == "__main__":
    run()
