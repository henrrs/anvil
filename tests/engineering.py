#!/usr/bin/env python3
"""Offline engineering-state, recovery, architecture and transfer regressions."""

from __future__ import annotations

import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from engineering import context, engine, invariants, repository, specification, store, verification
from engineering.contracts import validate_models
from engineering.errors import EngineeringError


sys.path.insert(0, str(ROOT / "evals/engineering"))
from harness import models, prepare, implement_unit, replay
from review_cases import evaluate as evaluate_cases


class EngineeringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="anvil-engineering-test-")
        self.base = pathlib.Path(self.temporary.name)
        self.environment = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.base / "state"),
            "XDG_DATA_HOME": str(self.base / "data"), "ANVIL_ENGINEERING": "auto",
            "PYTHONPATH": str(ROOT / "tests/fixtures/network-denied")})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def assert_code(self, code, callback, *args):
        with self.assertRaises(EngineeringError) as raised:
            callback(*args)
        self.assertEqual(code, raised.exception.code)

    def test_fast_path_escalation_and_disable_without_state(self):
        for request in ("Rename one field", "Fix one validation", "Update the README", "Change a test assertion"):
            self.assertEqual(specification.assess(request, {"files": 1})["workflow"], "DIRECT")
        local_in_complex_repo = specification.assess("Fix null handling in PartitionPlanner", {
            "requirements": 120, "subsystems": 12, "files": 500, "milestones": 8,
            "acceptance_criteria": 60, "cross_component": True,
        })
        self.assertEqual(local_in_complex_repo["workflow"], "DIRECT")
        self.assertEqual(len(local_in_complex_repo["project_context"]), 6)
        self.assertEqual(local_in_complex_repo["state_created"], False)
        long_local_request = specification.assess("Fix one local condition. " + "context " * 1000, {"files": 500})
        self.assertEqual(long_local_request["workflow"], "DIRECT")
        self.assertIn("long_request_text", long_local_request["project_context"])
        self.assertEqual(specification.assess("Change the state ownership boundary", {"state_ownership_change": True})["workflow"], "EXPAND")
        self.assertEqual(specification.assess("Implement a migration", {"migration": True})["workflow"], "EXPAND")
        with mock.patch.dict(os.environ, {"ANVIL_ENGINEERING": "off"}):
            self.assertEqual(specification.assess("Large task", {"migration": True})["workflow"], "DIRECT")
        self.assertFalse(store.state_root().exists())
        self.assertFalse((self.base / "data").exists())

    def test_semantic_inventory_does_not_invent_requirements(self):
        source = ROOT / "evals/engineering/ingestion/specification.md"
        result = specification.analyze(source)
        self.assertEqual(result["status"], "SEMANTIC_ANALYSIS_REQUIRED")
        self.assertNotIn("requirements", result)
        self.assertTrue(result["headings"])

    def test_invalid_models_graphs_and_imported_verification(self):
        project = prepare(self.base)
        for mutation in (
            lambda m: m["work"]["tasks"][0].update(depends_on=["T4"]),
            lambda m: m["work"]["tasks"][0].update(requirement_ids=["missing"]),
            lambda m: m["architecture"]["boundaries"][0].update(depends_on=["runtime"]),
            lambda m: m["requirements"]["items"][0].update(status="VERIFIED"),
        ):
            value = models()
            mutation(value)
            with self.assertRaises(EngineeringError):
                engine.create("invalid", project, project / "specification.md", value)
        value = models()
        value["work"]["tasks"][0]["paths"] = ["../escaped"]
        self.assert_code("SPECIFICATION_INVALID", validate_models, value)

    def test_dependency_implementation_and_completion_are_distinct(self):
        project = prepare(self.base)
        state = engine.create("test", project, project / "specification.md", models())
        self.assert_code("BLOCKED_DEPENDENCY", engine.start, state, project, "T2")
        engine.start(state, project, "T1")
        self.assertEqual(state["models"]["requirements"]["items"][0]["status"], "IN_PROGRESS")
        for name in ("contracts.py", "inputs.py"):
            shutil.copy2(ROOT / "evals/engineering/ingestion/solution" / name, project / name)
        engine.implement(state, project, "T1", ["contracts.py", "inputs.py"])
        self.assertEqual(engine.tasks(state)["T1"]["status"], "IMPLEMENTED")
        self.assert_code("VERIFICATION_FAILED", engine.finish, state, project)
        engine.check(state, project, "T1", "C1")
        self.assertEqual(engine.tasks(state)["T1"]["status"], "VERIFIED")
        self.assertNotEqual(state["models"]["work"]["milestones"][0]["status"], "COMPLETE")
        engine.checkpoint(state, project)
        self.assertEqual(state["models"]["work"]["milestones"][0]["status"], "COMPLETE")

    def test_milestone_checkpoint_checks_only_missing_scoped_invariants(self):
        project = prepare(self.base)
        state = engine.create("milestone-scope", project, project / "specification.md", models())
        engine.start(state, project, "T1")
        for name in ("contracts.py", "inputs.py"):
            shutil.copy2(ROOT / "evals/engineering/ingestion/solution" / name, project / name)
        engine.implement(state, project, "T1", ["contracts.py", "inputs.py"])
        engine.check(state, project, "T1", "C1")
        result = engine.checkpoint(state, project, milestone_id="M1")
        self.assertEqual(result, {"A1": "PASS"})
        self.assertEqual(engine.conformance(state), {"A1": "PASS", "A2": "UNKNOWN", "A3": "UNKNOWN", "A4": "UNKNOWN"})
        self.assertEqual(state["models"]["work"]["milestones"][0]["status"], "COMPLETE")
        self.assert_code("VERIFICATION_FAILED", engine.checkpoint, state, project, "M2")

    def test_ingestion_interruption_compaction_and_coverage(self):
        state, project, path = replay(self.base)
        self.assertEqual(state["status"], "COMPLETE")
        self.assertFalse(engine.coverage(state)["unverified_required"])
        self.assertEqual(set(engine.conformance(state).values()), {"PASS"})
        packet = context.resume(store.load(path), project)
        for key in ("objective", "architecture", "requirements", "current_milestone", "current_task", "blockers", "completed_tasks", "verification", "next_action", "coverage"):
            self.assertIn(key, packet)
        self.assertEqual(len(packet["completed_tasks"]), 4)
        self.assertFalse((self.base / "data").exists(), "engineering polluted durable memory")

    def test_unrelated_scheduler_transfer(self):
        state, _, _ = replay(self.base, "scheduler")
        self.assertEqual(engine.coverage(state)["counts"]["VERIFIED"], 7)
        self.assertEqual(state["status"], "COMPLETE")

    def test_stale_file_invalidates_dependents_only_and_resume_is_read_only(self):
        state, project, path = replay(self.base, interrupt=False)
        before = path.read_bytes()
        (project / "execution.py").write_text((project / "execution.py").read_text() + "\n# external change\n")
        packet = context.resume(store.load(path), project)
        self.assertEqual(packet["status"], "WORK_STATE_STALE")
        self.assertEqual(packet["completed_tasks"], ["T1", "T2"])
        self.assertFalse(packet["completion"]["ready"])
        self.assertEqual(path.read_bytes(), before)
        result = engine.revalidate(state, project, "Observed external execution edit")
        self.assertEqual(result["affected_tasks"], ["T3", "T4"])
        self.assertEqual(engine.tasks(state)["T1"]["status"], "VERIFIED")
        self.assertEqual(engine.conformance(state), {"A1": "PASS", "A2": "PASS", "A3": "PASS", "A4": "PASS"})
        self.assert_code("VERIFICATION_FAILED", engine.finish, state, project)

    def test_spec_change_replans_affected_requirements(self):
        state, project, _ = replay(self.base, interrupt=False)
        spec = project / "specification.md"
        spec.write_text(spec.read_text() + "\nNew acceptance clarification.\n")
        self.assert_code("REQUIREMENT_CONFLICT", engine.revalidate, state, project, "New specification")
        revised = models()
        revised["requirements"]["items"][-1]["statement"] += " with an additional failure assertion"
        engine.replan(state, project, spec, revised, "New failure acceptance criterion")
        self.assertEqual(engine.tasks(state)["T1"]["status"], "VERIFIED")
        self.assertEqual(engine.tasks(state)["T4"]["status"], "IMPLEMENTED")
        self.assertEqual(state["counters"]["replanned"], 1)

    def test_architecture_leak_regressions_and_semantic_unknown(self):
        project = prepare(self.base)
        for invariant, file, import_line in (("A1", "contracts.py", "import pyspark"),
                                             ("A2", "sources.py", "from planner import choose"),
                                             ("A3", "progress.py", "from planner import Plan"),
                                             ("A4", "planner.py", "import execution")):
            rule = next(i for i in models()["architecture"]["invariants"] if i["id"] == invariant)
            (project / file).write_text(import_line + "\n")
            self.assertEqual(invariants.evaluate(project, rule)["result"], "FAIL")
        rule = {"id": "A5", "statement": "One retry owner", "kind": "semantic", "paths": ["progress.py"]}
        self.assertEqual(invariants.evaluate(project, rule)["result"], "UNKNOWN")

    def test_failed_action_requires_changed_evidence_or_hypothesis(self):
        project = prepare(self.base)
        value = models()
        value["work"]["tasks"][0]["checks"][0]["argv"] = [sys.executable, "-c", "raise SystemExit(7)"]
        state = engine.create("retry", project, project / "specification.md", value)
        engine.start(state, project, "T1")
        for name in ("contracts.py", "inputs.py"):
            shutil.copy2(ROOT / "evals/engineering/ingestion/solution" / name, project / name)
        engine.implement(state, project, "T1", ["contracts.py", "inputs.py"])
        self.assertEqual(engine.check(state, project, "T1", "C1")["result"], "FAIL")
        self.assert_code("REPEATED_FAILED_ACTION", engine.check, state, project, "T1", "C1")
        self.assertEqual(engine.check(state, project, "T1", "C1", "New interpreter failure evidence")["result"], "FAIL")
        self.assertEqual(engine.tasks(state)["T1"]["status"], "IMPLEMENTED")

    def test_atomic_generations_cas_corruption_and_recovery(self):
        project = prepare(self.base)
        state = engine.create("atomic", project, project / "specification.md", models())
        path = store.task_path(project, "atomic")
        first = store.save(path, state, None)
        second = store.save(path, first, 1)
        self.assert_code("WORK_STATE_STALE", store.save, path, first, 1)
        original = path.read_bytes()
        real_replace = store.os.replace
        def interrupted(source, target):
            if target == path:
                raise OSError("simulated interruption before publish")
            return real_replace(source, target)
        with mock.patch.object(store.os, "replace", side_effect=interrupted):
            with self.assertRaises(OSError):
                store.save(path, second, 2)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        path.write_text('{"partial":')
        self.assert_code("WORK_STATE_CORRUPTED", store.load, path)
        recovered = store.recover(path, 2)
        self.assertTrue(recovered["recovery_required"])
        self.assertEqual(store.load(path)["revision"], 3)

    def test_hard_interruption_preserves_last_published_generation(self):
        project = prepare(self.base)
        path = store.task_path(project, "crash")
        state = store.save(path, engine.create("crash", project, project / "specification.md", models()), None)
        script = "import os,sys; from pathlib import Path; from engineering import store; p=Path(sys.argv[1]); s=store.load(p); real=store.os.replace; store.os.replace=lambda a,b: os._exit(71) if b==p else real(a,b); store.save(p,s,1)"
        proc = subprocess.run([sys.executable, "-c", script, str(path)], env={**os.environ, "PYTHONPATH": str(ROOT / "scripts")})
        self.assertEqual(proc.returncode, 71)
        self.assertEqual(store.load(path)["revision"], state["revision"])
        self.assertFalse(engine.completion(store.load(path))["ready"])

    def test_cli_concurrent_stale_mutation_executes_nothing(self):
        project = prepare(self.base)
        path = store.task_path(project, "race")
        store.save(path, engine.create("race", project, project / "specification.md", models()), None)
        command = [sys.executable, str(ROOT / "scripts/engineering.py"), "start", "--repository", str(project), "--id", "race", "--revision", "1", "--task", "T1", "--format", "json"]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        for process in processes:
            process.communicate(timeout=20)
        self.assertEqual(sorted(p.returncode for p in processes), [0, 2])
        self.assertEqual(store.load(path)["counters"]["started"], 1)

    def test_symlink_escape_secret_and_command_bounds(self):
        project = prepare(self.base)
        (project / "linked.py").symlink_to(self.base / "outside")
        self.assert_code("UNSAFE_PATH", repository.hashes, project, ["linked.py"])
        value = models()
        value["requirements"]["objective"] = "Bearer " + "x" * 30
        self.assert_code("SPECIFICATION_INVALID", validate_models, value)
        result = verification.run([sys.executable, "-c", "import time; time.sleep(5)"], project, 1)
        self.assertEqual(result["reason"], "CHECK_TIMEOUT")
        result = verification.run([sys.executable, "-c", "print('x'*3000000)"], project, 3)
        self.assertEqual(result["reason"], "CHECK_OUTPUT_LIMIT")

    def test_semantic_unknown_and_required_deferral_block_completion(self):
        state, project, _ = replay(self.base, interrupt=False)
        state["models"]["architecture"]["invariants"].append({"id": "A5", "statement": "One retry owner", "kind": "semantic", "paths": ["execution.py"]})
        self.assert_code("VERIFICATION_FAILED", engine.finish, state, project)
        engine.review(state, project, "A5", "PASS", "Inspected executor and source: only executor owns replay, with sink identity deduplication", "model")
        engine.finish(state, project)
        self.assertEqual(engine.latest(state, invariant_id="A5")["kind"], "semantic_review")
        state["models"]["requirements"]["items"].append({"id": "R99", "statement": "Additional required work", "type": "functional", "priority": "required", "source": {"document": "specification.md", "section": "Acceptance"}, "status": "DEFERRED", "disposition_reason": "Unresolved dependency"})
        self.assert_code("VERIFICATION_FAILED", engine.finish, state, project)

    def test_changed_check_definition_cannot_reuse_old_pass(self):
        state, _, _ = replay(self.base, interrupt=False)
        engine.tasks(state)["T1"]["checks"][0]["argv"] = [sys.executable, "-c", "raise SystemExit(2)"]
        engine.refresh(state)
        self.assertEqual(engine.tasks(state)["T1"]["status"], "IMPLEMENTED")
        self.assertFalse(engine.passed(state, "C1"))

    def test_malformed_types_and_missing_spec_are_actionable(self):
        for field in ({"status": []}, {"source": []}, {"source": {"document": "spec", "section": "x", "lines": [2, 1]}}):
            value = models()
            value["requirements"]["items"][0].update(field)
            self.assert_code("SPECIFICATION_INVALID", validate_models, value)
        project = prepare(self.base)
        state = engine.create("missing", project, project / "specification.md", models())
        (project / "specification.md").unlink()
        self.assertEqual(context.resume(state, project)["status"], "WORK_STATE_STALE")

    def test_concurrent_verification_runs_command_once(self):
        project = prepare(self.base)
        value = models()
        value["work"]["tasks"][0]["checks"][0]["argv"] = [sys.executable, "-c", "import time; from pathlib import Path; p=Path('effect-count'); time.sleep(.2); p.write_text(p.read_text()+'x' if p.exists() else 'x')"]
        state = engine.create("once", project, project / "specification.md", value)
        engine.start(state, project, "T1")
        for name in ("contracts.py", "inputs.py"):
            shutil.copy2(ROOT / "evals/engineering/ingestion/solution" / name, project / name)
        engine.implement(state, project, "T1", ["contracts.py", "inputs.py"])
        path = store.task_path(project, "once")
        store.save(path, state, None)
        command = [sys.executable, str(ROOT / "scripts/engineering.py"), "check", "--repository", str(project), "--id", "once", "--revision", "1", "--task", "T1", "--check", "C1"]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        for process in processes:
            process.communicate(timeout=20)
        self.assertEqual(sorted(p.returncode for p in processes), [0, 2])
        self.assertEqual((project / "effect-count").read_text(), "x")

    def test_cross_level_dependency_deadlock_and_scope_reduction(self):
        value = models()
        value["work"]["tasks"][0]["depends_on"] = ["T2"]
        value["work"]["tasks"][1]["depends_on"] = []
        self.assert_code("BLOCKED_DEPENDENCY", validate_models, value)
        state, project, _ = replay(self.base, interrupt=False)
        revised = models()
        revised["requirements"]["items"][-1]["priority"] = "optional"
        self.assert_code("REQUIREMENT_CONFLICT", engine.replan, state, project, project / "specification.md", revised, "Convenient scope reduction")

    def test_installed_helpers_work_on_both_runtime_profiles_without_state(self):
        for major in (1, 2):
            generated = self.base / f"config-{major}"
            env = {**os.environ, "HOME": str(self.base / "home"), "XDG_CONFIG_HOME": str(self.base / "config"), "ANVIL_ROOT": str(ROOT)}
            subprocess.run(["bash", "-c", 'source "$ANVIL_ROOT/scripts/lib/common.sh"; source "$ANVIL_ROOT/scripts/lib/install.sh"; anvil_build_config "$1" "" no "$2"', "_", str(generated), str(major)], env=env, check=True, capture_output=True)
            request = self.base / "request.txt"
            request.write_text("Rename a field")
            result = subprocess.run([sys.executable, str(generated / "scripts/engineering.py"), "assess", "--request", str(request), "--format", "json"], env=env, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)["workflow"], "DIRECT")
            self.assertTrue((generated / "skills/anvil-system-design/SKILL.md").is_file())
        self.assertFalse(store.state_root().exists())

    def test_technical_case_structure_cannot_claim_semantic_pass(self):
        suite = json.loads((ROOT / "evals/engineering/spark-cases.json").read_text())
        answer = {"id": "unknown-slow", "decision": "Locate the bottleneck before changing resources", "evidence": [{"claim": "Only a slow-job symptom is supplied", "confidence": "UNKNOWN", "source": "case request; execution evidence missing"}], "alternatives": ["Source wait", "Execution/conversion", "Startup"], "trade_off": "Gather a targeted timeline before running a potentially expensive experiment", "verification": ["Inspect plan, stage/task distribution, runtime and source timing"], "confidence": "UNKNOWN", "unknowns": ["Dominant physical mechanism"]}
        report = evaluate_cases(suite, [answer], [])
        self.assertEqual(report["results"][0]["structure"], "PASS")
        self.assertEqual(report["results"][0]["semantic"], "PENDING_SEMANTIC_REVIEW")
        answer["private_reasoning"] = "not allowed"
        self.assert_code("SPECIFICATION_INVALID", evaluate_cases, suite, [answer], [])

    def test_invalid_evidence_is_corruption_and_credentials_are_rejected(self):
        project = prepare(self.base)
        state = engine.create("invalid-record", project, project / "specification.md", models())
        path = store.task_path(project, "invalid-record")
        saved = store.save(path, state, None)
        saved["verification"] = [{}]
        path.write_bytes(store._encode(saved))
        self.assert_code("WORK_STATE_CORRUPTED", store.load, path)
        value = models()
        value["requirements"]["metadata"] = {"access_token": "private-value"}
        self.assert_code("SPECIFICATION_INVALID", validate_models, value)

    def test_large_coverage_is_counted_without_flooding_resume(self):
        project = prepare(self.base)
        value = models()
        for number in range(100):
            value["requirements"]["items"].append({"id": f"Extra{number}", "statement": "Additional explicit scope", "priority": "required", "type": "functional", "source": {"document": "specification.md", "section": "Scope"}})
        state = engine.create("bounded", project, project / "specification.md", value)
        packet = context.resume(state, project)
        self.assertEqual(packet["coverage"]["total"], 112)
        self.assertEqual(len(packet["coverage"]["unverified_required"]), 20)
        self.assertEqual(packet["coverage"]["unverified_required_omitted"], 92)
        self.assertFalse(packet["completion"]["ready"])

    def test_changed_head_requires_acknowledgement_even_when_files_match(self):
        state, project, _ = replay(self.base, interrupt=False)
        subprocess.run(["git", "-C", str(project), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "external head", "--allow-empty"], check=True)
        packet = context.resume(copy.deepcopy(state), project)
        self.assertEqual(packet["status"], "WORK_STATE_STALE")
        self.assertFalse(packet["completion"]["ready"])
        engine.revalidate(state, project, "Inspected HEAD-only change; all relevant files and assumptions match")
        self.assertTrue(engine.completion(state)["ready"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
