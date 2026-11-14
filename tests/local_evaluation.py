#!/usr/bin/env python3
"""Focused regressions for the live local OpenCode evaluation harness."""

from __future__ import annotations

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
