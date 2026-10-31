#!/usr/bin/env python3
"""Combine runtime and optional Databricks capability state."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import runtime  # noqa: E402
from public_errors import run_public  # noqa: E402
from communication import inputs as communication_inputs  # noqa: E402
from analysis.profiling import MAX_PROFILE_CELLS, MAX_ROWS, MAX_SOURCE_BYTES  # noqa: E402


def analysis_state() -> dict:
    return {
        "status": "AVAILABLE",
        "interface": "lazy anvil-communication skill and local analyze.py helper",
        "capabilities": ["scope_preserving_task_briefs", "bounded_tabular_profiling", "candidate_grain_and_entity_semantics",
                         "semantic_model_contract", "evidence_based_semantic_roles_v2", "entity_event_key_separation",
                         "confidence_and_abstention", "bounded_composite_grain", "question_and_plan_contracts", "deterministic_generic_primitives",
                         "cohort_comparison", "category_composition_comparison", "additive_contribution_analysis",
                         "executed_claim_validation", "reusable_semantic_profiles", "evidence_linked_findings",
                         "explainable_materiality_tiers", "artifact_independent_results", "communication_artifact_adapter"],
        "inputs": {"supported": ["csv", "tsv", "flat-json-row-array", "jsonl"],
                   "max_source_bytes": MAX_SOURCE_BYTES, "max_complete_rows": MAX_ROWS,
                   "max_profile_cells": MAX_PROFILE_CELLS,
                   "nested_json_cells": False},
        "depths": {"FAST": {"max_questions": 4, "max_operations": 4},
                   "STANDARD": {"max_questions": 12, "max_operations": 12},
                   "DEEP": {"max_questions": 20, "max_operations": 20}},
        "dependencies": {"required": [], "network": False, "persistent_state": False},
        "limitations": ["Semantic interpretation, question generation, materiality judgment, and narrative require model reasoning.",
                        "Offline deterministic fixtures do not measure real-model claim fidelity, latency, or token use."],
    }


def communication_state() -> dict:
    supported_inputs = ["markdown", "text", "csv", "tsv", "json", "jsonc-text", "source", "configuration",
                        "docx-text", "pptx-slide-text", "xlsx-cell-text"]
    optional_inputs = ["pdf-text"] if communication_inputs.shutil.which("pdftotext") else []
    return {
        "status": "AVAILABLE",
        "interface": "anvil-communication skill and local deterministic helper",
        "capabilities": ["evidence_inventory", "bounded_text_extraction", "quantitative_analysis",
                         "quantitative_visual_selection", "six_audience_lenses", "scenario_and_epistemic_contracts",
                         "editorial_selection_and_critique", "semantic_visual_intent", "motion_storyboard_static_fallback",
                         "audience_and_constraint_planning", "markdown_materialization", "architecture_svg",
                         "measurable_svg_geometry_review", "artifact_review"],
        "inputs": {"supported": supported_inputs, "optional": optional_inputs,
                   "media_analysis": False, "notes": [
                       "OOXML extraction reads supported text and values only; images, charts, media, and embedded objects are not analyzed.",
                       "Spreadsheet formulas are not recalculated; scanned PDF pages are not OCR-processed."]},
        "outputs": {"available": ["markdown_report", "markdown_slide_outline", "accessible_svg_architecture"],
                    "unavailable": ["pptx", "docx", "pdf", "quantitative_charts", "ocr", "dynamic_animation"]},
        "dependencies": {"required": [], "optional": ["pdftotext"]},
    }


def engineering_state() -> dict:
    return {"status": "DISABLED" if os.environ.get("ANVIL_ENGINEERING") == "off" else "AVAILABLE",
            "activation": "progressive; short tasks use the direct workflow without state",
            "interface": "anvil-engineering / anvil-system-design skills and local engineering.py helper",
            "models": ["requirements", "architecture", "work"],
            "capabilities": ["atomic_task_state", "requirements_coverage", "dependency_checks", "bounded_resume",
                             "repository_drift", "replanning", "architecture_invariants", "explicit_semantic_reviews",
                             "failure_aware_checks", "progressive_spark_references"],
            "state": "XDG_STATE_HOME/anvil/engineering; separate from durable memory; created explicitly",
            "runtime_independent": True, "model_independent": True, "required_dependencies": [],
            "limitations": ["Semantic extraction/design/review require agent judgment.",
                            "Resume never executes work or proves external-operation idempotency.",
                            "Deterministic fixtures do not measure real-model task success."]}


def databricks_module():
    path = ROOT / "scripts" / "databricks.py"
    spec = importlib.util.spec_from_file_location("anvil_databricks_adapter", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Databricks capability adapter could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--binary")
    parser.add_argument("--major", type=int)
    args = parser.parse_args()
    adapter = databricks_module()
    runtime_state = runtime.capabilities(args.binary, args.major)
    databricks_state = adapter.local_status()
    databricks_capabilities = adapter.capabilities(databricks_state)
    communication = communication_state()
    analysis = analysis_state()
    engineering = engineering_state()
    if args.format == "json":
        print(json.dumps({
            "schema_version": 1,
            "anvil_version": runtime_state["anvil_version"],
            "runtime": runtime_state,
            "databricks": databricks_state,
            "databricks_capabilities": databricks_capabilities,
            "communication": communication,
            "analysis": analysis,
            "engineering": engineering,
        }, indent=2))
        return 0

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "runtime.py"), "capabilities", "--format", "text", *(
            ["--binary", args.binary] if args.binary else []
        ), *(["--major", str(args.major)] if args.major is not None else [])],
        check=False,
    )
    if result.returncode:
        return result.returncode
    print()
    print(adapter.status_text(databricks_state, verbose=args.verbose))
    print("Databricks capabilities")
    from databricks_providers.presentation import capabilities_text
    print("\n".join("  " + line if index else line for index, line in
                      enumerate(capabilities_text(databricks_capabilities).splitlines())))
    print()
    print("Communication & artifacts")
    print("  Status                 AVAILABLE")
    print("  Inputs                 " + ", ".join(communication["inputs"]["supported"]))
    if communication["inputs"]["optional"]:
        print("  Optional inputs        " + ", ".join(communication["inputs"]["optional"]))
    print("  Outputs                Markdown, slide outline, accessible SVG")
    print("  Editorial planning     Six audience lenses, materiality, appendix selection, semantic visual intent")
    print("  Critic                 Optional deterministic candidate signals; semantic review remains pending")
    print()
    print("Intent & analytical intelligence")
    print("  Status                 AVAILABLE (lazy skill; standard-library local helper)")
    print("  Inputs                 CSV, TSV, flat JSON rows, JSON Lines; bounded local sources")
    print("  Depth                  FAST 4, STANDARD 12, DEEP 20 planned questions/operations")
    print("  State                  None; task-local results only")
    print("  Unavailable renderers  PPTX, DOCX, PDF, quantitative charts, OCR, animation")
    print()
    print("Engineering & system design")
    print("  Status                 " + engineering["status"])
    print("  Activation             Complex tasks; direct fast path for small edits")
    print("  Models                 Requirements, architecture, work (separate from memory)")
    print("  Resume                 Bounded, stale-aware; no automatic execution")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_public(main, command="Anvil capabilities"))
