#!/usr/bin/env python3
"""Focused regressions for the live local OpenCode evaluation harness."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals/engineering"))
import local_runner


class LocalEvaluationTests(unittest.TestCase):
    def test_new_evaluation_ids_are_unique_and_path_safe(self):
        first = local_runner.new_evaluation_id()
        second = local_runner.new_evaluation_id()

        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^anvil-engineering-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")
        self.assertTrue(local_runner.EVALUATION_ID_PATTERN.fullmatch(first))

    def test_default_budget_and_results_paths_are_external_and_evaluation_scoped(self):
        with tempfile.TemporaryDirectory(prefix="anvil-eval-state-") as temporary:
            state_home = pathlib.Path(temporary) / "state"
            namespace = argparse.Namespace(
                mode="smoke", evaluation_id="anvil-eval-path-check", budget_config=None,
                budget_state=None, output=None, benchmark_manifest=None,
            )
            with mock.patch.dict(local_runner.os.environ, {"XDG_STATE_HOME": str(state_home)}):
                directory = local_runner.configure_evaluation_paths(namespace)

            self.assertEqual(directory, state_home / "anvil/evaluations/engineering/anvil-eval-path-check")
            self.assertEqual(namespace.budget_config, directory / "budget.json")
            self.assertEqual(namespace.budget_state, directory / "budget-state.json")
            self.assertEqual(namespace.output, directory / "results.json")
            self.assertFalse(namespace.output.resolve().is_relative_to(ROOT))
            self.assertEqual(namespace.benchmark_manifest, local_runner.DEFAULT_BENCHMARKS)

    def test_budget_config_pins_unique_id_manifest_runtime_and_existing_limits(self):
        with tempfile.TemporaryDirectory(prefix="anvil-eval-budget-") as temporary:
            root = pathlib.Path(temporary)
            manifest = root / "benchmarks.json"
            manifest.write_text("{}\n", encoding="utf-8")
            config_path = root / "budget.json"
            executable = root / "opencode"
            executable.touch()

            local_runner.create_budget_config(
                config_path, "evaluation-test", executable,
                {"version": "1.19.5"}, "openai/gpt-6-luna", "high", manifest,
            )
            config = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertEqual(config["evaluation_id"], "evaluation-test")
            self.assertEqual(config["runtime"]["version"], "1.19.5")
            self.assertEqual(config["runtime"]["major"], 1)
            self.assertEqual(config["resource_budget"], local_runner.RESOURCE_BUDGET)
            self.assertEqual(config["benchmarks_sha256"], local_runner.hashlib.sha256(manifest.read_bytes()).hexdigest())

    def test_live_manifest_covers_supported_fixtures_and_external_graders(self):
        manifest = json.loads(local_runner.DEFAULT_BENCHMARKS.read_text(encoding="utf-8"))
        scenarios = {item["fixture"]: item for item in manifest["scenarios"]}

        self.assertEqual(set(scenarios), set(local_runner.LIVE_FIXTURES))
        for name, item in scenarios.items():
            grader = ROOT / item["private_grader"]
            self.assertTrue(grader.is_file(), name)
            self.assertEqual(local_runner.hashlib.sha256(grader.read_bytes()).hexdigest(),
                             item["private_grader_sha256"], name)
            self.assertTrue((ROOT / "evals/engineering" / name / "specification.md").is_file(), name)

    def test_local_runner_accepts_opencode_1_and_rejects_other_runtime_generations(self):
        with tempfile.TemporaryDirectory(prefix="anvil-eval-runtime-major-") as temporary:
            root = pathlib.Path(temporary)
            executable = root / "opencode"
            with mock.patch.object(local_runner.subprocess, "run",
                                   return_value=subprocess.CompletedProcess([], 0, "1.19.5\n", "")):
                runtime = local_runner.local_runtime_preflight(executable, root, "openai/gpt-6-luna")
            self.assertEqual(runtime["version"], "1.19.5")

            with mock.patch.object(local_runner.subprocess, "run",
                                   return_value=subprocess.CompletedProcess([], 0, "2.0.0\n", "")):
                with self.assertRaisesRegex(local_runner.EvaluationBlocked, "OpenCode 1.x only"):
                    local_runner.local_runtime_preflight(executable, root, "openai/gpt-6-luna")

    def test_active_landlock_helper_keeps_filesystem_and_network_boundaries(self):
        helper = ROOT / "evals/engineering/local_landlock_shell.c"
        source = helper.read_text(encoding="utf-8")
        build_source = pathlib.Path(local_runner._build_shell.__code__.co_filename).read_text(encoding="utf-8")

        self.assertTrue(helper.is_file())
        self.assertIn("local_landlock_shell.c", build_source)
        self.assertIn("LANDLOCK_ACCESS_FS_WRITE_FILE", source)
        self.assertIn("PR_SET_NO_NEW_PRIVS", source)
        self.assertIn("SECCOMP_MODE_FILTER", source)
        self.assertIn("__NR_socket", source)
        self.assertIn("__NR_connect", source)

    def test_prepared_model_workspace_excludes_private_acceptance_grader(self):
        with tempfile.TemporaryDirectory(prefix="anvil-eval-grader-scope-") as temporary:
            project = local_runner.prepare_model(pathlib.Path(temporary), "fast-control")
            grader = local_runner._run.private_grader("fast-control").resolve()

            self.assertTrue(grader.is_file())
            self.assertFalse(grader.is_relative_to(project.resolve()))
            self.assertFalse(any(path.name == "acceptance.py" for path in project.rglob("*.py")))

    def test_anvil_engineering_trigger_covers_explicit_dependent_phases(self):
        instructions = (ROOT / "config/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("An explicit sequence of phases whose outputs feed later phases is a trigger", instructions)
        self.assertIn("filesystem activation/rollback, and CLI integration", instructions)

    def test_fixture_edits_allow_relative_patch_paths_without_opening_external_paths(self):
        with tempfile.TemporaryDirectory(prefix="anvil-eval-policy-") as temporary:
            root = pathlib.Path(temporary)
            project = root / "project"
            project.mkdir()
            readable_skill = root / "anvil-config/skills/anvil-engineering"
            readable_skill.mkdir(parents=True)
            state_root = root / "isolated-state"
            state_root.mkdir()
            shell = root / "landlock-shell"

            config = local_runner._permissions(
                project, "anvil", shell, [readable_skill, state_root], state_root
            )
            permissions = config["agent"]["anvil"]["permission"]
            edit = permissions["edit"]

            self.assertEqual(edit["*"], "deny")
            self.assertEqual(edit["**"], "allow")
            self.assertEqual(edit["../**"], "deny")
            self.assertNotIn("limit.py", edit)
            self.assertEqual(edit[str(project.resolve()) + "/**"], "allow")
            self.assertEqual(edit["opencode.json"], "deny")
            self.assertEqual(edit[".git/**"], "deny")
            self.assertEqual(edit[str(readable_skill.resolve()) + "/**"], "deny")
            self.assertEqual(edit[str(state_root.resolve()) + "/**"], "allow")

    def test_metadata_probes_isolate_user_data_and_drop_credential_environment(self):
        with tempfile.TemporaryDirectory(prefix="anvil-eval-metadata-") as temporary:
            root = pathlib.Path(temporary)
            environment = {
                "HOME": str(root / "home"),
                "PATH": "/usr/bin:/bin",
                "XDG_CONFIG_HOME": str(root / "user-config"),
                "XDG_DATA_HOME": str(root / "user-data"),
                "XDG_STATE_HOME": str(root / "user-state"),
                "OPENAI_API_KEY": "must-not-be-forwarded",
                "DATABRICKS_TOKEN": "must-not-be-forwarded",
            }
            with mock.patch.dict(local_runner.os.environ, environment, clear=True):
                with mock.patch.object(local_runner.subprocess, "run",
                                       return_value=subprocess.CompletedProcess([], 0, "[]", "")) as run:
                    code, output = local_runner.invoke_metadata(pathlib.Path("/fake/opencode"),
                                                               ["debug", "skill"], root)
                child = run.call_args.kwargs["env"]

            self.assertEqual((code, output), (0, "[]"))
            self.assertEqual(child["HOME"], environment["HOME"])
            self.assertEqual(child["XDG_CONFIG_HOME"], environment["XDG_CONFIG_HOME"])
            self.assertNotEqual(child["XDG_DATA_HOME"], environment["XDG_DATA_HOME"])
            self.assertNotEqual(child["XDG_STATE_HOME"], environment["XDG_STATE_HOME"])
            self.assertNotIn("OPENAI_API_KEY", child)
            self.assertNotIn("DATABRICKS_TOKEN", child)
            self.assertTrue(pathlib.Path(child["XDG_DATA_HOME"]).is_relative_to(pathlib.Path(tempfile.gettempdir())))

    def test_runtime_log_diagnostics_read_xdg_logs_without_retaining_messages(self):
        with tempfile.TemporaryDirectory(prefix="anvil-eval-runtime-log-") as temporary:
            root = pathlib.Path(temporary)
            data_home = root / "user-data"
            log = data_home / "opencode/log/opencode.log"
            log.parent.mkdir(parents=True)
            log.write_text(
                '{"level":"error","provider":"openai","error":{"status":401,'
                '"message":"Unauthorized sk-private-example"}}\n',
                encoding="utf-8",
            )
            prompt_history = root / "state/opencode/prompt-history.jsonl"
            prompt_history.parent.mkdir(parents=True)
            prompt_history.write_text('{"prompt":"PRIVATE USER PROMPT"}\n', encoding="utf-8")

            evidence = local_runner._run.inspect_runtime_logs(
                root / "home", data_home, root / "state", root / "cache"
            )
            serialized = json.dumps(evidence)

            self.assertEqual(evidence["provider_category"], "AUTHENTICATION_OR_PROVIDER_ACCESS")
            self.assertEqual(evidence["http_status"], 401)
            self.assertEqual(evidence["provider_id"], "openai")
            self.assertEqual(evidence["files"], 1)
            self.assertEqual(evidence["bytes"], log.stat().st_size)
            self.assertNotIn("Unauthorized", serialized)
            self.assertNotIn("sk-private-example", serialized)
            self.assertNotIn("PRIVATE USER PROMPT", serialized)
            self.assertIn("sha256", serialized)

            stale = local_runner._run.inspect_runtime_logs(
                root / "home", data_home, root / "state", root / "cache",
                since_epoch=log.stat().st_mtime + 1,
            )
            self.assertEqual(stale["files"], 0)

    def test_local_runtime_database_failure_is_classified_without_retaining_stderr(self):
        with tempfile.TemporaryDirectory(prefix="anvil-eval-runtime-error-") as temporary:
            trace = pathlib.Path(temporary) / "trace.jsonl"
            process = subprocess.Popen(
                [sys.executable, "-c", "import sys; sys.stderr.write('Database is not empty and has no session table')"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
            )
            metrics = local_runner._run.stream_metrics(process, 10, 4096, trace)

            self.assertEqual(metrics["failure_class"], "LOCAL_RUNTIME_STATE_ERROR")
            self.assertIsNone(metrics["provider_category"])
            self.assertNotIn("Database is not empty", trace.read_text(encoding="utf-8"))

    def test_treatment_task_prompt_is_neutral(self):
        prompt = local_runner.challenge_prompt()
        self.assertIn("repository-provided instructions and skills when applicable", prompt)
        self.assertNotIn("when this treatment is Anvil", prompt)
        self.assertNotIn("Use Anvil's loaded", prompt)

    def test_safe_trace_counts_failed_patch_separately_and_keeps_error_text_private(self):
        failed = {
            "type": "tool_use",
            "part": {"type": "tool", "callID": "call-failed", "tool": "apply_patch",
                     "state": {"status": "error", "input": {"patchText": "PRIVATE PATCH"},
                               "error": "PRIVATE TOOL ERROR"}},
        }
        succeeded = {
            "type": "tool_use",
            "part": {"type": "tool", "callID": "call-success", "tool": "bash",
                     "state": {"status": "completed", "input": {"command": "true"}}},
        }
        script = "import json; print(json.dumps(" + repr(failed) + ")); print(json.dumps(" + repr(succeeded) + "))"
        with tempfile.TemporaryDirectory(prefix="anvil-eval-trace-") as temporary:
            trace = pathlib.Path(temporary) / "trace.jsonl"
            process = subprocess.Popen(
                [sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,
            )
            metrics = local_runner._run.stream_metrics(process, 10, 4096, trace)

            self.assertEqual(metrics["tool_calls"], 2)
            self.assertEqual(metrics["tool_completed"], 1)
            self.assertEqual(metrics["tool_errors"], 1)
            safe_trace = trace.read_text(encoding="utf-8")
            self.assertIn('"tool_error":true', safe_trace)
            self.assertNotIn("PRIVATE PATCH", safe_trace)
            self.assertNotIn("PRIVATE TOOL ERROR", safe_trace)


if __name__ == "__main__":
    unittest.main(verbosity=2)
